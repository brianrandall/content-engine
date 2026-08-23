import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import ollama

try:
    from app.research import search_web, analyze_research, generate_content
except ImportError:
    from research import search_web, analyze_research, generate_content

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL = "qwen3:8b"


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

    print("Content Engine Telegram bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()