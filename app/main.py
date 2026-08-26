import os
import asyncio
import threading
from pathlib import Path

from dotenv import load_dotenv
from app.run_state import ProductionRunState
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
import ollama

try:
    from app.pipeline import run_pipeline
except ImportError:
    from pipeline import run_pipeline

try:
    from app.research import (
        search_web,
        analyze_research,
        generate_content,
    )
except ImportError:
    from research import (
        search_web,
        analyze_research,
        generate_content,
    )

try:
    from app.trends import (
        collect_trends,
        rank_trending_topics,
    )
except ImportError:
    from trends import (
        collect_trends,
        rank_trending_topics,
    )

try:
    from app.publisher import (
        load_manifest,
        publish_instagram,
        publish_youtube,
    )
except ImportError:
    from publisher import (
        load_manifest,
        publish_instagram,
        publish_youtube,
    )


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path(
    __file__
).resolve().parents[1]

load_dotenv(
    BASE_DIR / ".env"
)

TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

MODEL = "qwen3:8b"

ACTIVE_RUN = None
ACTIVE_RUN_LOCK = threading.Lock()


# =========================================================
# PRODUCTION RUN
# =========================================================

async def _run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
    run_state: ProductionRunState,
):
    """
    Run the content production pipeline.

    /run <topic>
        Use a manually supplied topic.

    /run
        Automatically discover and select
        multiple stories from current trends.

    Generated videos are published to Instagram.
    Telegram is used for status notifications only.
    """

    niche = " ".join(
        context.args
    ).strip()
    selected_topics = None
    selection_diagnostics = {}

    run_state.update(current_topic=None)

    # -----------------------------------------------------
    # AUTONOMOUS TOPIC DISCOVERY
    # -----------------------------------------------------

    if not niche:

        opening = (
            "🧪 LOCAL TEST RUN\n\n"
            "⚠️ Publishing is DISABLED.\n\n"
            "📡 Scanning current trends..."
            if mode == "local"
            else "🔥 Autonomous run\n\n"
            "📡 Scanning current trends..."
        )

        await update.message.reply_text(
            opening
        )

        try:

            trends = await asyncio.to_thread(
                collect_trends,
                hackernews_limit=10,
            )

            if not trends:

                await update.message.reply_text(
                    "❌ Trend collection returned "
                    "no usable trends."
                )

                return

            run_state.update(selected=0)
            await update.message.reply_text(
                f"📡 Found {len(trends)} trends.\n"
                "🧠 Evaluating opportunities..."
            )

            topics = await asyncio.to_thread(
                rank_trending_topics,
                trends,
                8,
            )
            selection_diagnostics = getattr(
                rank_trending_topics,
                "last_diagnostics",
                {},
            )
            if not isinstance(selection_diagnostics, dict):
                selection_diagnostics = {}

        except Exception as exc:

            if run_state.cancel_event.is_set():
                await update.message.reply_text(
                    "🛑 RUN STOPPED\n\n"
                    "Completed: 0\n"
                    "Failed: 0\n"
                    "Cancelled: 0\n"
                    "Skipped: 0"
                )
                return

            await update.message.reply_text(
                "❌ Trend discovery failed.\n\n"
                f"{type(exc).__name__}: {exc}"
            )

            return

        if not topics:

            await update.message.reply_text(
                "❌ Trend discovery returned "
                "no usable topics."
            )

            return

        await update.message.reply_text(
            "🎯 Selected "
            f"{len(topics)} stories:\n\n"
            + "\n".join(
                f"{index}. {topic['topic']}\n"
                f"   Category: {topic['category']}\n"
                f"   Score: {topic.get('adjusted_score', 'n/a')}"
                for index, topic in enumerate(topics, 1)
            )
            + "\n\n🎬 Starting production..."
        )

        selected_topics = topics

    # -----------------------------------------------------
    # MANUAL TOPIC
    # -----------------------------------------------------

    else:

        await update.message.reply_text(
            "🚀 Starting production run...\n\n"
            f"Topic: {niche}\n"
            "Videos: 8\n\n"
            "Using manually supplied topic."
        )

    # -----------------------------------------------------
    # PRODUCTION PIPELINE
    # -----------------------------------------------------

    try:

        run_info = await asyncio.to_thread(
            run_pipeline,
            niche=niche,
            content_count=8,
            selected_topics=selected_topics,
            mode=mode,
            cancellation_event=run_state.cancel_event,
            status_callback=run_state.update,
            selection_diagnostics=selection_diagnostics,
        )

    except Exception as exc:

        await update.message.reply_text(
            "❌ Production run failed.\n\n"
            f"{type(exc).__name__}: {exc}"
        )

        return

    completed_videos = run_info["completed_videos"]
    video_records = run_info["video_records"]
    run_state.update(
        selected=len(run_info["selected_topics"]),
        completed=len(completed_videos),
        failed=sum(
            record["status"] == "failed"
            for record in video_records
        ),
        skipped=sum(
            record["status"] == "skipped"
            for record in video_records
        ),
        cancelled=sum(
            record["status"] == "cancelled"
            for record in video_records
        ),
        current_topic=None,
    )

    failed_records = [
        record
        for record in video_records
        if record["status"] == "failed"
    ]
    failure_text = ""

    if failed_records:
        failure_text = "\n\nFailed:\n" + "\n".join(
            f"- {record['topic']} — {record.get('reason', 'Unknown error')}"
            for record in failed_records
        )

    cancelled_count = sum(
        record["status"] == "cancelled"
        for record in video_records
    )
    summary_title = (
        "🛑 RUN STOPPED"
        if cancelled_count
        else (
            "🧪 LOCAL RUN COMPLETE"
            if mode == "local"
            else "🔥 Production complete!"
        )
    )
    summary_suffix = (
        "\n\n📁 Videos saved locally.\n"
        "🚫 Nothing was published."
        if mode == "local"
        else "\n\n📤 Publishing is delegated to the publisher layer."
    )

    await update.message.reply_text(
        f"{summary_title}\n\n"
        f"Selected: {len(run_info['selected_topics'])}\n"
        f"Completed: {len(completed_videos)}\n"
        f"Failed: {len(failed_records)}\n"
        f"Cancelled: {cancelled_count}\n"
        f"Skipped: {sum(record['status'] == 'skipped' for record in video_records)}"
        f"{failure_text}\n\n"
        f"{summary_suffix}"
    )

    if mode == "local" or run_state.cancel_event.is_set():
        return

    if not completed_videos:
        return

    published = []
    failed = []

    for index, video_path in enumerate(
        completed_videos,
        1,
    ):

        if run_state.cancel_event.is_set():
            return

        video_file = Path(video_path)
        video_dir = video_file.parent

        if not video_file.exists():
            failed.append({
                "index": index,
                "path": str(video_file),
                "error": "File does not exist.",
            })
            await update.message.reply_text(
                f"⚠️ Video {index} missing.\n{video_file}"
            )
            continue

        manifest_path = video_dir / "manifest.json"
        manifest = load_manifest(manifest_path)
        social = manifest.get("social", {})
        youtube_status = social.get("youtube", {}).get("status", "pending")
        instagram_status = social.get("instagram", {}).get("status", "pending")

        await update.message.reply_text(
            f"📤 Publishing Reel {index}/{len(completed_videos)}..."
        )

        result = {
            "video_generated": True,
            "youtube": {"status": youtube_status},
            "instagram": {"status": instagram_status},
        }

        try:
            youtube_result = await asyncio.to_thread(
                publish_youtube,
                video_dir,
            )
            result["youtube"] = youtube_result
        except Exception as exc:
            result["youtube"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed.append({
                "index": index,
                "platform": "youtube",
                "error": result["youtube"]["error"],
            })

        try:
            instagram_result = await asyncio.to_thread(
                publish_instagram,
                video_dir,
            )
            result["instagram"] = instagram_result
        except Exception as exc:
            result["instagram"] = {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed.append({
                "index": index,
                "platform": "instagram",
                "error": result["instagram"]["error"],
            })

        if (
            result["youtube"].get("status") == "published"
            or result["instagram"].get("status") == "published"
        ):
            published.append({
                "index": index,
                "result": result,
            })

        youtube_state = result["youtube"].get("status", "pending")
        instagram_state = result["instagram"].get("status", "pending")
        await update.message.reply_text(
            f"📊 Reel {index} status\n"
            f"YouTube: {youtube_state}\n"
            f"Instagram: {instagram_state}"
        )

    message = (
        "🏁 RUN COMPLETE\n\n"
        f"Topic: {niche}\n"
        f"Videos generated: {len(completed_videos)}/"
        f"{len(run_info['selected_topics'])}\n"
        f"Videos with at least one successful publish: {len(published)}\n"
        f"Publish failures: {len(failed)}"
    )

    if published:
        message += "\n\n🔥 Successful platform results:\n"
        for item in published:
            youtube_status = item["result"].get("youtube", {}).get("status", "pending")
            instagram_status = item["result"].get("instagram", {}).get("status", "pending")
            youtube_id = item["result"].get("youtube", {}).get("post_id", "unknown")
            instagram_id = item["result"].get("instagram", {}).get("media_id", "unknown")
            message += (
                f"• Reel {item['index']} — "
                f"YouTube {youtube_status} {youtube_id} / "
                f"Instagram {instagram_status} {instagram_id}\n"
            )

    if failed:
        message += "\n⚠️ Platform failures:\n"
        for item in failed:
            message += f"• Video {item['index']} ({item['platform']}): {item['error']}\n"

    await update.message.reply_text(message)


async def _start_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
):
    global ACTIVE_RUN

    with ACTIVE_RUN_LOCK:
        if ACTIVE_RUN is not None:
            await update.message.reply_text(
                "⚠️ A production run is already active.\n\n"
                "Use /stop to cancel it or wait for it to finish."
            )
            return

        ACTIVE_RUN = ProductionRunState(mode=mode)
        run_state = ACTIVE_RUN

    try:
        return await _run(
            update,
            context,
            mode,
            run_state,
        )
    finally:
        run_state.update(
            status="idle",
            current_topic=None,
        )
        with ACTIVE_RUN_LOCK:
            if ACTIVE_RUN is run_state:
                ACTIVE_RUN = None


async def run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    return await _start_run(
        update,
        context,
        "publish",
    )


async def run_local(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    return await _start_run(
        update,
        context,
        "local",
    )


async def stop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    with ACTIVE_RUN_LOCK:
        run_state = ACTIVE_RUN

    if run_state is None:
        await update.message.reply_text(
            "ℹ️ No production run is currently active."
        )
        return

    if run_state.request_stop():
        await update.message.reply_text(
            "🛑 Production stop requested.\n\n"
            "The current operation will finish, then the run will stop."
        )
    else:
        await update.message.reply_text(
            "🛑 Production is already stopping."
        )


# =========================================================
# RESEARCH
# =========================================================

async def research(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = " ".join(
        context.args
    )

    if not query:

        await update.message.reply_text(
            "Usage:\n"
            "/research your topic here"
        )

        return

    await update.message.reply_text(
        "🔎 Searching..."
    )

    results = search_web(
        query
    )

    if not results:

        await update.message.reply_text(
            "Couldn't find anything..."
        )

        return

    await update.message.reply_text(
        f"🧠 Found {len(results)} sources. "
        "Sending them to local Ollama "
        "for analysis..."
    )

    analysis = analyze_research(
        query,
        results,
    )

    await update.message.reply_text(
        f"🔎 Research Brief\n\n"
        f"{analysis}"
    )


# =========================================================
# STATUS
# =========================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    with ACTIVE_RUN_LOCK:
        run_state = ACTIVE_RUN

    if run_state is not None:
        snapshot = run_state.snapshot()
        mode = snapshot["mode"].upper()
        current = snapshot["current_topic"] or "Between topics"
        await update.message.reply_text(
            "🤖 Content Engine\n\n"
            f"Status: {snapshot['status'].upper()}\n"
            f"Mode: {mode}\n"
            f"Selected: {snapshot['selected']}\n"
            f"Completed: {snapshot['completed']}\n"
            f"Failed: {snapshot['failed']}\n"
            f"Cancelled: {snapshot['cancelled']}\n"
            f"Skipped: {snapshot['skipped']}\n"
            f"Current topic: {current}"
        )
        return

    await update.message.reply_text(
        "🤖 Content Engine\n\n"
        "Status: IDLE\n"
        "LLM: Ollama (local)\n"
        f"Model: {MODEL}\n"
        "Instagram: ENABLED"
    )


# =========================================================
# ASK
# =========================================================

async def ask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    question = " ".join(
        context.args
    )

    if not question:

        await update.message.reply_text(
            "Usage:\n"
            "/ask your question here"
        )

        return

    await update.message.reply_text(
        "🧠 Thinking..."
    )

    response = await asyncio.to_thread(
        ollama.chat,
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": question,
            }
        ],
    )

    answer = response[
        "message"
    ][
        "content"
    ]

    await update.message.reply_text(
        answer
    )


# =========================================================
# CONTENT
# =========================================================

async def content(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = " ".join(
        context.args
    )

    if not query:

        await update.message.reply_text(
            "Usage:\n"
            "/content your topic here"
        )

        return

    await update.message.reply_text(
        "🔎 Researching..."
    )

    results = search_web(
        query
    )

    if not results:

        await update.message.reply_text(
            "Couldn't find anything."
        )

        return

    await update.message.reply_text(
        f"🧠 Found {len(results)} sources.\n"
        "Reading and analyzing..."
    )

    research = analyze_research(
        query,
        results,
    )

    await update.message.reply_text(
        "✍️ Turning research into "
        "a content package..."
    )

    content_package = generate_content(
        query,
        research,
    )

    await update.message.reply_text(
        f"🎬 CONTENT PACKAGE\n\n"
        f"{content_package}"
    )


# =========================================================
# APPLICATION
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to the project .env file."
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "status",
            status,
        )
    )

    app.add_handler(
        CommandHandler(
            "ask",
            ask,
        )
    )

    app.add_handler(
        CommandHandler(
            "research",
            research,
        )
    )

    app.add_handler(
        CommandHandler(
            "content",
            content,
        )
    )

    app.add_handler(
        CommandHandler(
            "run",
            run,
        )
    )

    app.add_handler(
        CommandHandler(
            "runlocal",
            run_local,
        )
    )

    app.add_handler(
        CommandHandler(
            "stop",
            stop,
        )
    )

    print(
        "Content Engine Telegram bot running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()