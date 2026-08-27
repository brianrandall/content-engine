import os
import asyncio
import threading
import subprocess
import signal
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

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL = "qwen3:8b"

SCHEDULER_PID_FILE = Path("/tmp/content-engine-scheduler.pid")
SCHEDULER_LOG_FILE = Path("/tmp/content-engine-scheduler.log")
SCHEDULER_OWNER_FILE = Path("/tmp/content-engine-scheduler-telegram.pid")
TELEGRAM_CHAT_ID_FILE = Path("/tmp/content-engine-telegram-chat-id")
RUN_SCRIPT = BASE_DIR / "run.sh"

ACTIVE_RUN = None
ACTIVE_RUN_LOCK = threading.Lock()


# =========================================================
# SCHEDULER CONTROL
# =========================================================

def _read_scheduler_pid():
    try:
        pid_text = SCHEDULER_PID_FILE.read_text(encoding="utf-8").strip()
        pid = int(pid_text)
    except (OSError, ValueError):
        return None

    if pid <= 0:
        return None

    return pid


def _scheduler_is_running(pid=None):
    if pid is None:
        pid = _read_scheduler_pid()

    if pid is None:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False

    return True


def _start_scheduler():
    """Start ./run.sh in its own process session if it is not running."""

    if not RUN_SCRIPT.exists():
        raise RuntimeError(f"run.sh not found: {RUN_SCRIPT}")

    if not os.access(RUN_SCRIPT, os.X_OK):
        raise RuntimeError("run.sh is not executable. Run: chmod +x run.sh")

    existing_pid = _read_scheduler_pid()
    if _scheduler_is_running(existing_pid):
        return existing_pid, False

    try:
        SCHEDULER_PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    log_handle = open(SCHEDULER_LOG_FILE, "a", encoding="utf-8")

    try:
        process = subprocess.Popen(
            ["/bin/zsh", str(RUN_SCRIPT)],
            cwd=BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except Exception:
        log_handle.close()
        raise

    log_handle.close()

    # run.sh writes its authoritative PID file after startup. Give it a
    # moment to do so, but fall back to the PID returned by Popen.
    for _ in range(20):
        pid = _read_scheduler_pid()
        if pid is not None and _scheduler_is_running(pid):
            SCHEDULER_OWNER_FILE.write_text(str(pid), encoding="utf-8")
            return pid, True
        if process.poll() is not None:
            break
        import time
        time.sleep(0.1)

    if process.poll() is not None:
        raise RuntimeError(
            "run.sh exited during startup. "
            f"See {SCHEDULER_LOG_FILE}"
        )

    SCHEDULER_OWNER_FILE.write_text(str(process.pid), encoding="utf-8")
    return process.pid, True


def _stop_scheduler():
    """Stop the scheduler process started by run.sh."""

    pid = _read_scheduler_pid()
    if pid is None:
        return False, "No scheduler PID file found."

    if not _scheduler_is_running(pid):
        try:
            SCHEDULER_PID_FILE.unlink(missing_ok=True)
            SCHEDULER_OWNER_FILE.unlink(missing_ok=True)
        except OSError:
            pass
        return False, "Scheduler was not running."

    owned_by_telegram = False
    try:
        owned_by_telegram = (
            SCHEDULER_OWNER_FILE.read_text(encoding="utf-8").strip() == str(pid)
        )
    except OSError:
        pass

    try:
        if owned_by_telegram:
            # /run starts run.sh in its own session. Terminating the process
            # group also terminates an in-progress pipeline child instead of
            # leaving a production job orphaned behind the scheduler.
            os.killpg(pid, signal.SIGTERM)
        else:
            # A scheduler started manually in a terminal may share the
            # terminal's process group, so only terminate the scheduler PID.
            os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        raise RuntimeError(f"Could not stop scheduler PID {pid}: {exc}") from exc
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    try:
        SCHEDULER_OWNER_FILE.unlink(missing_ok=True)
    except OSError:
        pass

    return True, f"Stop signal sent to scheduler process group {pid}."


# =========================================================
# PRODUCTION RUN
# =========================================================

async def _production_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
    run_state: ProductionRunState,
):
    """Run the production pipeline directly from Telegram."""

    niche = " ".join(context.args).strip()
    selected_topics = None
    selection_diagnostics = {}

    run_state.update(current_topic=None)

    if not niche:
        opening = (
            "LOCAL TEST RUN\n\n"
            "Publishing is DISABLED.\n\n"
            "Scanning current trends..."
            if mode == "local"
            else "Autonomous run\n\nScanning current trends..."
        )

        await update.message.reply_text(opening)

        try:
            trends = await asyncio.to_thread(
                collect_trends,
                hackernews_limit=10,
            )

            if not trends:
                await update.message.reply_text(
                    "Trend collection returned no usable trends."
                )
                return

            run_state.update(selected=0)
            await update.message.reply_text(
                f"Found {len(trends)} trends.\n"
                "Evaluating opportunities..."
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
                    "RUN STOPPED\n\n"
                    "Completed: 0\n"
                    "Failed: 0\n"
                    "Cancelled: 0\n"
                    "Skipped: 0"
                )
                return

            await update.message.reply_text(
                "Trend discovery failed.\n\n"
                f"{type(exc).__name__}: {exc}"
            )
            return

        if not topics:
            await update.message.reply_text(
                "Trend discovery returned no usable topics."
            )
            return

        await update.message.reply_text(
            "Selected "
            f"{len(topics)} stories:\n\n"
            + "\n".join(
                f"{index}. {topic['topic']}\n"
                f"   Category: {topic['category']}\n"
                f"   Score: {topic.get('adjusted_score', 'n/a')}"
                for index, topic in enumerate(topics, 1)
            )
            + "\n\nStarting production..."
        )

        selected_topics = topics

    else:
        await update.message.reply_text(
            "Starting production run...\n\n"
            f"Topic: {niche}\n"
            "Videos: 8\n\n"
            "Using manually supplied topic."
        )

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
            "Production run failed.\n\n"
            f"{type(exc).__name__}: {exc}"
        )
        return

    completed_videos = run_info["completed_videos"]
    video_records = run_info["video_records"]
    run_state.update(
        selected=len(run_info["selected_topics"]),
        completed=len(completed_videos),
        failed=sum(record["status"] == "failed" for record in video_records),
        skipped=sum(record["status"] == "skipped" for record in video_records),
        cancelled=sum(record["status"] == "cancelled" for record in video_records),
        current_topic=None,
    )

    failed_records = [
        record for record in video_records if record["status"] == "failed"
    ]
    failure_text = ""
    if failed_records:
        failure_text = "\n\nFailed:\n" + "\n".join(
            f"- {record['topic']} — {record.get('reason', 'Unknown error')}"
            for record in failed_records
        )

    cancelled_count = sum(
        record["status"] == "cancelled" for record in video_records
    )
    summary_title = (
        "RUN STOPPED"
        if cancelled_count
        else (
            "LOCAL RUN COMPLETE"
            if mode == "local"
            else "Production complete!"
        )
    )
    summary_suffix = (
        "\n\nVideos saved locally.\n"
        "Nothing was published."
        if mode == "local"
        else "\n\nPublishing is delegated to the publisher layer."
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

    for index, video_path in enumerate(completed_videos, 1):
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
                f"Video {index} missing.\n{video_file}"
            )
            continue

        manifest_path = video_dir / "manifest.json"
        manifest = load_manifest(manifest_path)
        social = manifest.get("social", {})
        youtube_status = social.get("youtube", {}).get("status", "pending")
        instagram_status = social.get("instagram", {}).get("status", "pending")

        await update.message.reply_text(
            f"Publishing Reel {index}/{len(completed_videos)}..."
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
            published.append({"index": index, "result": result})

        youtube_state = result["youtube"].get("status", "pending")
        instagram_state = result["instagram"].get("status", "pending")
        await update.message.reply_text(
            f"Reel {index} status\n"
            f"YouTube: {youtube_state}\n"
            f"Instagram: {instagram_state}"
        )

    message = (
        "RUN COMPLETE\n\n"
        f"Topic: {niche}\n"
        f"Videos generated: {len(completed_videos)}/"
        f"{len(run_info['selected_topics'])}\n"
        f"Videos with at least one successful publish: {len(published)}\n"
        f"Publish failures: {len(failed)}"
    )

    if published:
        message += "\n\nSuccessful platform results:\n"
        for item in published:
            youtube_result = item["result"].get("youtube", {})
            instagram_result = item["result"].get("instagram", {})
            youtube_status = youtube_result.get("status", "pending")
            instagram_status = instagram_result.get("status", "pending")
            youtube_url = youtube_result.get("url") or youtube_result.get("permalink")
            instagram_url = instagram_result.get("permalink") or instagram_result.get("url")
            message += f"• Reel {item['index']}\n"
            message += f"  YouTube: {youtube_status}"
            if youtube_url:
                message += f"\n  {youtube_url}"
            message += f"\n  Instagram: {instagram_status}"
            if instagram_url:
                message += f"\n  {instagram_url}"
            message += "\n"

    if failed:
        message += "\nPlatform failures:\n"
        for item in failed:
            message += (
                f"• Video {item['index']} ({item['platform']}): "
                f"{item['error']}\n"
            )

    await update.message.reply_text(message)


async def _start_direct_run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: str,
):
    global ACTIVE_RUN

    with ACTIVE_RUN_LOCK:
        if ACTIVE_RUN is not None:
            await update.message.reply_text(
                "A production run is already active.\n\n"
                "Use /stop to cancel it or wait for it to finish."
            )
            return

        ACTIVE_RUN = ProductionRunState(mode=mode)
        run_state = ACTIVE_RUN

    try:
        return await _production_run(update, context, mode, run_state)
    finally:
        run_state.update(status="idle", current_topic=None)
        with ACTIVE_RUN_LOCK:
            if ACTIVE_RUN is run_state:
                ACTIVE_RUN = None


async def run_local(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Legacy/direct local test command; /run is reserved for run.sh."""
    return await _start_direct_run(update, context, "local")


# =========================================================
# TELEGRAM SCHEDULER COMMANDS
# =========================================================

async def run(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Start the long-running ./run.sh scheduler."""

    if context.args:
        await update.message.reply_text(
            "/run does not take arguments.\n\n"
            "It starts ./run.sh and its production scheduler."
        )
        return

    chat = update.effective_chat
    if chat is not None:
        TELEGRAM_CHAT_ID_FILE.write_text(
            str(chat.id),
            encoding="utf-8",
        )

    try:
        pid, started = await asyncio.to_thread(_start_scheduler)
    except Exception as exc:
        await update.message.reply_text(
            "❌ Could not start scheduler.\n\n"
            f"{type(exc).__name__}: {exc}"
        )
        return

    if started:
        await update.message.reply_text(
            "▶️ Scheduler started.\n\n"
            "./run.sh is now running in the background.\n"
            f"Scheduler PID: {pid}\n\n"
            "10:00 AM → batch (4 videos)\n"
            "Every 6 hours after → single video\n\n"
            "Use /stop to stop the scheduler."
        )
    else:
        await update.message.reply_text(
            "ℹ️ Scheduler is already running.\n\n"
            f"Scheduler PID: {pid}\n\n"
            "Use /stop to stop it."
        )


async def stop(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Stop ./run.sh without stopping the media server or Telegram bot."""

    try:
        stopped, message = await asyncio.to_thread(_stop_scheduler)
    except Exception as exc:
        await update.message.reply_text(
            "❌ Could not stop scheduler.\n\n"
            f"{type(exc).__name__}: {exc}"
        )
        return

    if stopped:
        await update.message.reply_text(
            "🛑 Scheduler stop requested.\n\n"
            "./run.sh is shutting down.\n"
            "Media server and Telegram bot remain running."
        )
    else:
        await update.message.reply_text(f"ℹ️ {message}")


# =========================================================
# RESEARCH
# =========================================================

async def research(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
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

    analysis = await asyncio.to_thread(analyze_research, query, results)
    await update.message.reply_text(f"🔎 Research Brief\n\n{analysis}")


# =========================================================
# STATUS
# =========================================================

async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    with ACTIVE_RUN_LOCK:
        run_state = ACTIVE_RUN

    scheduler_pid = _read_scheduler_pid()
    scheduler_running = _scheduler_is_running(scheduler_pid)

    if run_state is not None:
        snapshot = run_state.snapshot()
        mode = snapshot["mode"].upper()
        current = snapshot["current_topic"] or "Between topics"
        await update.message.reply_text(
            "🤖 Content Engine\n\n"
            f"Direct run: {snapshot['status'].upper()}\n"
            f"Mode: {mode}\n"
            f"Selected: {snapshot['selected']}\n"
            f"Completed: {snapshot['completed']}\n"
            f"Failed: {snapshot['failed']}\n"
            f"Cancelled: {snapshot['cancelled']}\n"
            f"Skipped: {snapshot['skipped']}\n"
            f"Current topic: {current}\n\n"
            f"Scheduler: {'RUNNING' if scheduler_running else 'STOPPED'}"
            + (f"\nScheduler PID: {scheduler_pid}" if scheduler_running else "")
        )
        return

    await update.message.reply_text(
        "🤖 Content Engine\n\n"
        "Telegram bot: ONLINE\n"
        f"Scheduler: {'RUNNING' if scheduler_running else 'STOPPED'}\n"
        + (f"Scheduler PID: {scheduler_pid}\n" if scheduler_running else "")
        + f"LLM: Ollama (local)\n"
        f"Model: {MODEL}\n"
        "Instagram: ENABLED\n"
        "YouTube: ENABLED"
    )


# =========================================================
# ASK
# =========================================================

async def ask(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    question = " ".join(context.args)

    if not question:
        await update.message.reply_text("Usage:\n/ask your question here")
        return

    await update.message.reply_text("🧠 Thinking...")
    response = await asyncio.to_thread(
        ollama.chat,
        model=MODEL,
        messages=[{"role": "user", "content": question}],
    )
    answer = response["message"]["content"]
    await update.message.reply_text(answer)


# =========================================================
# CONTENT
# =========================================================

async def content(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    query = " ".join(context.args)

    if not query:
        await update.message.reply_text("Usage:\n/content your topic here")
        return

    await update.message.reply_text("🔎 Researching...")
    results = await asyncio.to_thread(search_web, query)

    if not results:
        await update.message.reply_text("Couldn't find anything.")
        return

    await update.message.reply_text(
        f"🧠 Found {len(results)} sources.\nReading and analyzing..."
    )

    research_result = await asyncio.to_thread(
        analyze_research,
        query,
        results,
    )
    content_package = await asyncio.to_thread(
        generate_content,
        query,
        research_result,
    )

    await update.message.reply_text(
        f"🎬 CONTENT PACKAGE\n\n{content_package}"
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
        Application.builder()
        .token(TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("research", research))
    app.add_handler(CommandHandler("content", content))
    app.add_handler(CommandHandler("run", run))
    app.add_handler(CommandHandler("runlocal", run_local))
    app.add_handler(CommandHandler("stop", stop))

    print("Content Engine Telegram bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
