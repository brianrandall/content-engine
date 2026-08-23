import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import ollama

try:
    from app.pipeline import run_pipeline
except ImportError:
    from pipeline import run_pipeline

try:
    from app.research import search_web, analyze_research, generate_content
except ImportError:
    from research import search_web, analyze_research, generate_content

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL = "qwen3:8b"


async def run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    niche = " ".join(context.args)

    if not niche:
        niche = "AI automation"

    await update.message.reply_text(
        f"🚀 Starting production run...\n\n"
        f"Niche: {niche}\n"
        f"Videos: 5\n\n"
        "This will take a while. I'll send the videos here when they're finished."
    )

    try:
        completed_videos = await asyncio.to_thread(
            run_pipeline,
            niche,
            5,
        )

    except Exception as exc:
        await update.message.reply_text(
            f"❌ Production run failed.\n\n"
            f"{type(exc).__name__}: {exc}"
        )
        return

    if not completed_videos:
        await update.message.reply_text(
            "❌ Production finished, but no videos were created."
        )
        return

    await update.message.reply_text(
        f"🔥 Production complete!\n\n"
        f"Created {len(completed_videos)}/5 videos.\n"
        "Uploading..."
    )

    for index, video_path in enumerate(
        completed_videos,
        1,
    ):
        video_path = Path(video_path)

        if not video_path.exists():
            await update.message.reply_text(
                f"⚠️ Video {index} is missing:\n"
                f"{video_path}"
            )
            continue

        await update.message.reply_text(
            f"📤 Uploading video {index}/{len(completed_videos)}..."
        )

        with open(video_path, "rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                caption=f"🎬 Video {index}/{len(completed_videos)}",
            )

    await update.message.reply_text(
        "✅ Run finished."
    )


async def research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage:\n/research your topic here")
        return

    await update.message.reply_text("🔎 Searching...")

    results = search_web(query)

    if not results:
        await update.message.reply_text("Couldn't find anything...")
        return

    await update.message.reply_text(
        f"🧠 Found {len(results)} sources. "
        "Sending them to local Ollama for analysis..."
    )

    analysis = analyze_research(query, results)

    await update.message.reply_text(
        f"🔎 Research Brief\n\n{analysis}"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Content Engine\n\n"
        "Status: ONLINE\n"
        "LLM: Ollama (local)\n"
        f"Model: {MODEL}"
    )


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question = " ".join(context.args)

    if not question:
        await update.message.reply_text("Usage:\n/ask your question here")
        return

    await update.message.reply_text("🧠 Thinking...")

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": question,
            }
        ],
    )

    answer = response["message"]["content"]
    await update.message.reply_text(answer)

async def content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text(
            "Usage:\n/content your topic here"
        )
        return

    await update.message.reply_text(
        "🔎 Researching..."
    )

    results = search_web(query)

    if not results:
        await update.message.reply_text(
            "Couldn't find anything."
        )
        return

    await update.message.reply_text(
        f"🧠 Found {len(results)} sources.\n"
        "Reading and analyzing..."
    )

    research = analyze_research(query, results)

    await update.message.reply_text(
        "✍️ Turning research into a content package..."
    )

    content_package = generate_content(
        query,
        research,
    )

    await update.message.reply_text(
        f"🎬 CONTENT PACKAGE\n\n{content_package}"
    )


def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it to the project .env file.")

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("content", content))
    app.add_handler(CommandHandler("run", run))

    print("Content Engine Telegram bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()