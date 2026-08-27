"""Send scheduled Content Engine publication results to Telegram."""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID_FILE = Path("/tmp/content-engine-telegram-chat-id")
GRAPH_VERSION = "v23.0"


def _read_chat_id():
    value = os.getenv("CONTENT_ENGINE_TELEGRAM_CHAT_ID")
    if value:
        return value.strip()

    try:
        return CHAT_ID_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _instagram_permalink(media_id):
    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    if not token or not media_id:
        return None

    response = requests.get(
        f"https://graph.instagram.com/{GRAPH_VERSION}/{media_id}",
        params={
            "fields": "permalink",
            "access_token": token,
        },
        timeout=20,
    )

    if not response.ok:
        return None

    return response.json().get("permalink")


def _load_manifests(run_dir: Path):
    manifests = []
    for manifest_path in sorted(run_dir.rglob("manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        if isinstance(manifest, dict) and manifest.get("video_path"):
            manifests.append((manifest_path, manifest))

    return manifests


def _send_message(chat_id, text):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")

    response = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,
        },
        timeout=30,
    )
    response.raise_for_status()


def notify_run(run_dir: str | Path):
    run_dir = Path(run_dir).expanduser().resolve()
    chat_id = _read_chat_id()

    if not chat_id:
        print("Telegram notification skipped: no chat ID is known yet.")
        return False

    manifests = _load_manifests(run_dir)
    if not manifests:
        print(f"Telegram notification skipped: no manifests found in {run_dir}")
        return False

    lines = [
        "🔥 CONTENT ENGINE RUN COMPLETE",
        "",
        f"Run: {run_dir.name}",
        "",
    ]

    for index, (_, manifest) in enumerate(manifests, 1):
        title = manifest.get("title") or f"Video {index}"
        social = manifest.get("social", {})
        youtube = social.get("youtube", {})
        instagram = social.get("instagram", {})

        youtube_status = youtube.get("status", "unknown")
        youtube_url = youtube.get("url")
        if not youtube_url and youtube.get("post_id"):
            youtube_url = f"https://www.youtube.com/watch?v={youtube['post_id']}"

        instagram_status = instagram.get("status", "unknown")
        instagram_url = instagram.get("url")
        if instagram_status == "published" and instagram.get("post_id"):
            instagram_url = instagram_url or _instagram_permalink(instagram["post_id"])

        lines.append(f"🎬 {index}. {title}")
        lines.append(
            f"YouTube: {youtube_status}"
            + (f"\n{youtube_url}" if youtube_url else "")
        )
        lines.append(
            f"Instagram: {instagram_status}"
            + (f"\n{instagram_url}" if instagram_url else "")
        )
        lines.append("")

    _send_message(chat_id, "\n".join(lines).rstrip())
    print(f"Telegram publication notification sent for {run_dir}")
    return True


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 -m app.telegram_notify /path/to/run_directory")

    notify_run(sys.argv[1])


if __name__ == "__main__":
    main()
