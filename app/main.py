import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
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
    from app.instagram import (
        publish_reel,
    )
except ImportError:
    from instagram import (
        publish_reel,
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


# =========================================================
# PRODUCTION RUN
# =========================================================

async def run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    Run the content production pipeline.

    /run <topic>
        Use a manually supplied topic.

    /run
        Automatically discover and select
        a topic from current trends.

    Generated videos are published to Instagram.
    Telegram is used for status notifications only.
    """

    niche = " ".join(
        context.args
    ).strip()

    # -----------------------------------------------------
    # AUTONOMOUS TOPIC DISCOVERY
    # -----------------------------------------------------

    if not niche:

        await update.message.reply_text(
            "🔥 No topic supplied.\n\n"
            "Scanning current trends..."
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

            await update.message.reply_text(
                f"📡 Found {len(trends)} trends.\n"
                "Finding the strongest topic..."
            )

            topics = await asyncio.to_thread(
                rank_trending_topics,
                trends,
                5,
            )

        except Exception as exc:

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

        niche = topics[0][
            "topic"
        ]

        await update.message.reply_text(
            "🎯 Topic selected:\n\n"
            f"{niche}\n\n"
            "Starting production..."
        )

    # -----------------------------------------------------
    # MANUAL TOPIC
    # -----------------------------------------------------

    else:

        await update.message.reply_text(
            "🚀 Starting production run...\n\n"
            f"Topic: {niche}\n"
            "Videos: 5\n\n"
            "Using manually supplied topic."
        )

    # -----------------------------------------------------
    # PRODUCTION PIPELINE
    # -----------------------------------------------------

    try:

        completed_videos = await asyncio.to_thread(
            run_pipeline,
            niche,
            5,
        )

    except Exception as exc:

        await update.message.reply_text(
            "❌ Production run failed.\n\n"
            f"{type(exc).__name__}: {exc}"
        )

        return

    if not completed_videos:

        await update.message.reply_text(
            "❌ Production finished, "
            "but no videos were created."
        )

        return

    # -----------------------------------------------------
    # PRODUCTION COMPLETE
    # -----------------------------------------------------

    await update.message.reply_text(
        "🔥 Production complete!\n\n"
        f"Created {len(completed_videos)}/5 videos.\n\n"
        "📤 Publishing to Instagram..."
    )

    # -----------------------------------------------------
    # INSTAGRAM PUBLISHING
    # -----------------------------------------------------

    published = []
    failed = []

    for index, video_path in enumerate(
        completed_videos,
        1,
    ):

        video_path = Path(
            video_path
        )

        if not video_path.exists():

            failed.append({
                "index": index,
                "path": str(video_path),
                "error": "File does not exist.",
            })

            await update.message.reply_text(
                f"⚠️ Video {index} missing.\n"
                f"{video_path}"
            )

            continue

        await update.message.reply_text(
            f"📤 Publishing Reel "
            f"{index}/{len(completed_videos)}..."
        )

        try:

            result = await asyncio.to_thread(
                publish_reel,
                video_path,
                (
                    f"{niche}\n\n"
                    "🔥 Daily News Content"
                ),
            )

            published.append({
                "index": index,
                "result": result,
            })

            await update.message.reply_text(
                f"✅ Instagram Reel "
                f"{index} published."
            )

        except Exception as exc:

            failed.append({
                "index": index,
                "path": str(video_path),
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            })

            await update.message.reply_text(
                f"❌ Instagram Reel "
                f"{index} failed.\n\n"
                f"{type(exc).__name__}: {exc}"
            )

    # -----------------------------------------------------
    # FINAL REPORT
    # -----------------------------------------------------

    message = (
        "🏁 RUN COMPLETE\n\n"
        f"Topic: {niche}\n"
        f"Videos created: "
        f"{len(completed_videos)}/5\n"
        f"Instagram published: "
        f"{len(published)}\n"
        f"Failed: "
        f"{len(failed)}"
    )

    if published:

        message += (
            "\n\n🔥 Published:\n"
        )

        for item in published:

            media_id = item[
                "result"
            ].get(
                "media_id",
                "unknown",
            )

            message += (
                f"• Reel {item['index']} "
                f"— {media_id}\n"
            )

    if failed:

        message += (
            "\n⚠️ Failures:\n"
        )

        for item in failed:

            message += (
                f"• Video {item['index']}: "
                f"{item['error']}\n"
            )

    await update.message.reply_text(
        message
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
    await update.message.reply_text(
        "🤖 Content Engine\n\n"
        "Status: ONLINE\n"
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

    print(
        "Content Engine Telegram bot running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()