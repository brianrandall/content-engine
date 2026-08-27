"""Standalone Instagram publishing entry point.

Publishes an already-created Content Engine video without running
research, topic selection, or video production.
"""

import argparse
from pathlib import Path

from app.publisher import publish_instagram as _publish_instagram


def publish_video(video_path: str | Path):
    """Publish one existing final video using its sibling manifest."""

    video_path = Path(video_path).expanduser().resolve()

    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Video path is not a file: {video_path}")
    if video_path.suffix.lower() != ".mp4":
        raise ValueError(f"Expected an MP4 video: {video_path}")

    video_dir = video_path.parent
    manifest_path = video_dir / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError(
            "Cannot publish this video because its sibling "
            f"manifest.json is missing: {manifest_path}"
        )

    print("\n================================")
    print("INSTAGRAM PUBLISH")
    print("================================")
    print(f"Video: {video_path}")
    print(f"Manifest: {manifest_path}")

    result = _publish_instagram(video_dir)

    print("\n================================")
    print("INSTAGRAM PUBLISH COMPLETE")
    print("================================")

    if result:
        print(f"Media ID: {result.get('media_id')}")
        print(f"Status: {result.get('status')}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Publish an existing Content Engine video to Instagram."
    )
    parser.add_argument("video", help="Path to an existing final_short.mp4")
    args = parser.parse_args()
    publish_video(args.video)


if __name__ == "__main__":
    main()
