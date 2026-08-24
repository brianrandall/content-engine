import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from app.youtube import get_video_stats
except ImportError:
    from youtube import get_video_stats


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"


def update_video_stats(
    manifest_path: Path,
):
    """
    Update social statistics for one video manifest.
    """

    with open(
        manifest_path,
        "r",
        encoding="utf-8",
    ) as f:
        manifest = json.load(f)

    youtube = (
        manifest
        .get("social", {})
        .get("youtube", {})
    )

    if youtube.get("status") != "uploaded":
        return False

    post_id = youtube.get("post_id")

    if not post_id:
        return False

    stats = get_video_stats(post_id)

    youtube["stats"] = {
        "views": stats["views"],
        "likes": stats["likes"],
        "comments": stats["comments"],
        "shares": stats["shares"],
        "saves": stats["saves"],
    }

    youtube["published_at"] = (
        stats["published_at"]
    )

    youtube["stats_updated_at"] = (
        stats["stats_updated_at"]
    )

    youtube["error"] = None

    with open(
        manifest_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            manifest,
            f,
            indent=2,
            ensure_ascii=False,
        )

    return True


def find_manifests():
    """
    Find individual video manifests.
    """

    return sorted(
        path
        for path in OUTPUT_DIR.rglob(
            "manifest.json"
        )
        if path.parent != OUTPUT_DIR
    )


def sync_stats():
    """
    Refresh statistics for every uploaded video.
    """

    manifests = find_manifests()

    print(
        "\n================================"
    )
    print(
        "📊 SOCIAL STATS SYNC"
    )
    print(
        "================================"
    )

    print(
        f"\nFound {len(manifests)} "
        "video manifests."
    )

    updated = 0
    skipped = 0
    failed = 0

    for manifest_path in manifests:

        print(
            f"\n📄 {manifest_path}"
        )

        try:

            result = update_video_stats(
                manifest_path
            )

            if result:

                updated += 1

                print(
                    "   ✅ Stats updated."
                )

            else:

                skipped += 1

                print(
                    "   ⏭️ Not uploaded. Skipping."
                )

        except Exception as exc:

            failed += 1

            print(
                "   ❌ Failed:"
            )

            print(
                f"      {type(exc).__name__}: "
                f"{exc}"
            )

    print(
        "\n================================"
    )
    print(
        "📊 STATS SYNC COMPLETE"
    )
    print(
        "================================"
    )

    print(
        f"Updated: {updated}"
    )

    print(
        f"Skipped: {skipped}"
    )

    print(
        f"Failed: {failed}"
    )


if __name__ == "__main__":

    sync_stats()