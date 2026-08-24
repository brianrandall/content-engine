import os
import asyncio
import json
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


BASE_DIR = Path(__file__).resolve().parents[1]

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

    Telegram is used for control and notifications.
    Videos are NOT uploaded to Telegram.
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

        niche = topics[0]["topic"]

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
        "Checking publishing status..."
    )

    # -----------------------------------------------------
    # READ MANIFESTS
    # -----------------------------------------------------

    youtube_uploaded = 0
    youtube_pending = 0

    youtube_links = []

    for video_path in completed_videos:

        video_path = Path(
            video_path
        )

        manifest_path = (
            video_path.parent
            / "manifest.json"
        )

        if not manifest_path.exists():

            continue

        try:

            with open(
                manifest_path,
                "r",
                encoding="utf-8",
            ) as f:

                manifest = json.load(f)

        except Exception:

            continue

        youtube = (
            manifest
            .get("social", {})
            .get("youtube", {})
        )

        status = youtube.get(
            "status"
        )

        if status == "uploaded":

            youtube_uploaded += 1

            url = youtube.get(
                "url"
            )

            if url:

                youtube_links.append(
                    (
                        manifest.get(
                            "title",
                            "Untitled",
                        ),
                        url,
                    )
                )

        else:

            youtube_pending += 1

    # -----------------------------------------------------
    # TELEGRAM NOTIFICATION
    # -----------------------------------------------------

    message = (
        "✅ RUN COMPLETE\n\n"
        f"🎯 Topic:\n{niche}\n\n"
        f"🎬 Videos created: "
        f"{len(completed_videos)}/5\n\n"
        "📺 YouTube\n"
        f"Uploaded: "
        f"{youtube_uploaded}/"
        f"{len(completed_videos)}\n"
    )

    if youtube_pending:

        message += (
            f"Pending: "
            f"{youtube_pending}\n"
        )

    if youtube_links:

        message += (
            "\n🔗 YouTube videos:\n"
        )

        for title, url in youtube_links:

            message += (
                f"\n• {title}\n"
                f"{url}\n"
            )

    message += (
        "\n📱 TikTok: "
        "not connected yet\n"
        "📸 Instagram: "
        "not connected yet\n\n"
        "Telegram is notification-only."
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
        f"Model: {MODEL}"
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

    response = ollama.chat(
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