import json
from pathlib import Path
from datetime import datetime, timezone

from app.youtube import upload_video

from app.instagram import publish_reel


PLATFORMS = [
    "youtube",
    "instagram",
    "tiktok",
]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_social_manifest():
    return {
        platform: {
            "status": "pending",
            "post_id": None,
            "url": None,
            "published_at": None,
            "error": None,
            "stats": {
                "views": None,
                "likes": None,
                "comments": None,
                "shares": None,
                "saves": None,
            },
            "stats_updated_at": None,
        }
        for platform in PLATFORMS
    }


def load_manifest(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(path: Path, manifest: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            manifest,
            f,
            indent=2,
            ensure_ascii=False,
        )


def initialize_social_manifest(video_dir: Path):
    manifest_path = video_dir / "manifest.json"

    if not manifest_path.exists():
        raise RuntimeError(
            f"Missing video manifest: {manifest_path}"
        )

    manifest = load_manifest(manifest_path)

    if "social" not in manifest:
        manifest["social"] = create_social_manifest()

        save_manifest(
            manifest_path,
            manifest,
        )

    return manifest


def update_platform_status(
    video_dir: Path,
    platform: str,
    status: str,
    post_id=None,
    url=None,
    error=None,
):
    if platform not in PLATFORMS:
        raise ValueError(
            f"Unsupported platform: {platform}"
        )

    manifest_path = video_dir / "manifest.json"

    manifest = load_manifest(
        manifest_path
    )

    if "social" not in manifest:
        manifest["social"] = (
            create_social_manifest()
        )

    platform_data = manifest["social"][platform]

    platform_data["status"] = status

    if post_id is not None:
        platform_data["post_id"] = post_id

    if url is not None:
        platform_data["url"] = url

    if error is not None:
        platform_data["error"] = error

    if status == "published":
        platform_data["published_at"] = utc_now()

    save_manifest(
        manifest_path,
        manifest,
    )

    return manifest

def publish_youtube(video_dir: Path):
    manifest_path = video_dir / "manifest.json"

    manifest = load_manifest(
        manifest_path
    )

    video_path = Path(
        manifest["video_path"]
    )

    try:
        result = upload_video(
            video_path,
            manifest["title"],
            manifest.get("description", ""),
        )

        update_platform_status(
            video_dir,
            "youtube",
            "published",
            post_id=result["post_id"],
            url=result["url"],
        )

        return result

    except Exception as exc:

        update_platform_status(
            video_dir,
            "youtube",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
        )

        raise

def publish_instagram(video_dir: Path):
    manifest_path = video_dir / "manifest.json"

    manifest = load_manifest(
        manifest_path
    )

    video_path = Path(
        manifest["video_path"]
    )

    caption = manifest.get(
        "description",
        "",
    )

    try:
        result = publish_reel(
            video_path,
            caption=caption,
        )

        update_platform_status(
            video_dir,
            "instagram",
            "published",
            post_id=result["media_id"],
        )

        return result

    except Exception as exc:

        update_platform_status(
            video_dir,
            "instagram",
            "failed",
            error=f"{type(exc).__name__}: {exc}",
        )

        raise