"""Standalone YouTube publishing entry point.

Publishes an already-created Content Engine video without running
research, topic selection, or video production.
"""

import argparse
import json
from pathlib import Path

from app.youtube import upload_video


def _load_manifest(manifest_path: Path) -> dict:
    """Load and validate the sibling Content Engine manifest."""

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Manifest contains invalid JSON: {manifest_path}"
        ) from exc

    if not isinstance(manifest, dict):
        raise RuntimeError(
            f"Manifest must contain a JSON object: {manifest_path}"
        )

    return manifest


def _metadata_from_manifest(manifest: dict, video_path: Path):
    """Extract YouTube title/description from the Content Engine manifest."""

    title = (
        manifest.get("title")
        or manifest.get("content", {}).get("title")
        if isinstance(manifest.get("content", {}), dict)
        else manifest.get("title")
    )

    description = (
        manifest.get("description")
        or manifest.get("content", {}).get("description", "")
        if isinstance(manifest.get("content", {}), dict)
        else manifest.get("description", "")
    )

    if not isinstance(title, str) or not title.strip():
        raise RuntimeError(
            "Manifest is missing a usable title for YouTube publishing."
        )

    if not isinstance(description, str):
        description = ""

    return title.strip(), description.strip()


def publish_video(video_path: str | Path):
    """Publish one existing final video using its sibling manifest."""

    video_path = Path(video_path).expanduser().resolve()

    if not video_path.exists():
        raise FileNotFoundError(
            f"Video not found: {video_path}"
        )

    if not video_path.is_file():
        raise ValueError(
            f"Video path is not a file: {video_path}"
        )

    if video_path.suffix.lower() != ".mp4":
        raise ValueError(
            f"Expected an MP4 video: {video_path}"
        )

    video_dir = video_path.parent
    manifest_path = video_dir / "manifest.json"

    if not manifest_path.exists():
        raise RuntimeError(
            "Cannot publish this video because its sibling "
            f"manifest.json is missing: {manifest_path}"
        )

    manifest = _load_manifest(manifest_path)
    title, description = _metadata_from_manifest(
        manifest,
        video_path,
    )

    print("\n================================")
    print("📤 YOUTUBE PUBLISH")
    print("================================")
    print(f"Video: {video_path}")
    print(f"Manifest: {manifest_path}")
    print(f"Title: {title}")

    result = upload_video(
        video_path=video_path,
        title=title,
        description=description,
    )

    print("\n================================")
    print("✅ YOUTUBE PUBLISH COMPLETE")
    print("================================")

    print(f"Video ID: {result['post_id']}")
    print(f"URL:      {result['url']}")

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Publish an existing Content Engine video to YouTube."
    )
    parser.add_argument(
        "video",
        help="Path to an existing final_short.mp4",
    )

    args = parser.parse_args()
    publish_video(args.video)


if __name__ == "__main__":
    main()
