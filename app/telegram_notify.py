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
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
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


def _youtube_permalink(youtube):
    url = youtube.get("url") or youtube.get("permalink")

    if url:
        return url

    post_id = youtube.get("post_id")
    if post_id:
        return f"https://www.youtube.com/watch?v={post_id}"

    return None


def _instagram_permalink_from_manifest(instagram):
    url = instagram.get("url") or instagram.get("permalink")

    if url:
        return url

    post_id = instagram.get("post_id")

    if post_id and instagram.get("status") == "published":
        return _instagram_permalink(post_id)

    return None


def notify_run(run_dir: str | Path):
    run_dir = Path(run_dir).expanduser().resolve()
    chat_id = _read_chat_id()

    if not chat_id:
        print(
            "Telegram notification skipped: "
            "no chat ID is known yet."
        )
        return False

    manifests = _load_manifests(run_dir)

    if not manifests:
        print(
            f"Telegram notification skipped: "
            f"no manifests found in {run_dir}"
        )
        return False

    lines = [
        "🔥 CONTENT ENGINE",
        "",
        "VIDEO(S) CREATED",
        "",
    ]

    for index, (_, manifest) in enumerate(manifests, 1):
        title = manifest.get("title") or f"Video {index}"

        social = manifest.get("social", {})
        instagram = social.get("instagram", {})
        youtube = social.get("youtube", {})

        instagram_status = instagram.get("status", "unknown")
        youtube_status = youtube.get("status", "unknown")

        instagram_url = _instagram_permalink_from_manifest(
            instagram
        )
        youtube_url = _youtube_permalink(youtube)

        lines.append(f"{index}. {title}")
        lines.append("")

        if instagram_status == "published":
            lines.append("📸 INSTAGRAM PUBLISH COMPLETE")
            if instagram_url:
                lines.append(instagram_url)
        else:
            lines.append(
                f"📸 INSTAGRAM: {instagram_status}"
            )

        lines.append("")

        if youtube_status == "published":
            lines.append("📺 YOUTUBE PUBLISH COMPLETE")
            if youtube_url:
                lines.append(youtube_url)
        else:
            lines.append(
                f"📺 YOUTUBE: {youtube_status}"
            )

        lines.append("")
        lines.append("────────────────────")
        lines.append("")

    _send_message(
        chat_id,
        "\n".join(lines).rstrip(),
    )

    print(
        f"Telegram publication notification sent for {run_dir}"
    )

    return True


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: "
            "python3 -m app.telegram_notify "
            "/path/to/run_directory"
        )

    notify_run(sys.argv[1])


if __name__ == "__main__":
    main()