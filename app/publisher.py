import json
from pathlib import Path
from datetime import datetime, timezone

from app.youtube import upload_video
from app.instagram import (
    get_public_video_url,
    create_reel_container,
    wait_for_processing,
    publish_container,
)


PLATFORMS = [
    "youtube",
    "instagram",
    "tiktok",
]


def ensure_publishing_enabled(mode: str = "publish"):
    if mode == "local":
        raise RuntimeError(
            "Publishing is disabled in local mode."
        )


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_social_manifest():
    return {
        platform: {
            "status": "pending",
            "post_id": None,
            "container_id": None,
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
    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def save_manifest(
    path: Path,
    manifest: dict,
):
    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            manifest,
            f,
            indent=2,
            ensure_ascii=False,
        )


def initialize_social_manifest(
    video_dir: Path,
):
    manifest_path = (
        video_dir / "manifest.json"
    )

    if not manifest_path.exists():
        raise RuntimeError(
            f"Missing video manifest: "
            f"{manifest_path}"
        )

    manifest = load_manifest(
        manifest_path
    )

    changed = False

    if "social" not in manifest:

        manifest["social"] = (
            create_social_manifest()
        )

        changed = True

    else:

        # Upgrade older manifests that don't
        # have container_id yet.

        for platform in PLATFORMS:

            if platform not in manifest["social"]:

                manifest["social"][platform] = (
                    create_social_manifest()[
                        platform
                    ]
                )

                changed = True

            elif (
                "container_id"
                not in manifest["social"][platform]
            ):

                manifest["social"][platform][
                    "container_id"
                ] = None

                changed = True

    if changed:

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
    container_id=None,
    url=None,
    error=None,
):
    if platform not in PLATFORMS:
        raise ValueError(
            f"Unsupported platform: {platform}"
        )

    manifest_path = (
        video_dir / "manifest.json"
    )

    manifest = load_manifest(
        manifest_path
    )

    if "social" not in manifest:

        manifest["social"] = (
            create_social_manifest()
        )

    if platform not in manifest["social"]:

        manifest["social"][platform] = (
            create_social_manifest()[platform]
        )

    platform_data = (
        manifest["social"][platform]
    )

    platform_data["status"] = status

    if post_id is not None:

        platform_data["post_id"] = (
            post_id
        )

    if container_id is not None:

        platform_data["container_id"] = (
            container_id
        )

    if url is not None:

        platform_data["url"] = url

    if error is not None:

        platform_data["error"] = error

    elif status not in (
        "failed",
        "ready_to_publish",
    ):

        platform_data["error"] = None

    if status == "published":

        platform_data["published_at"] = (
            utc_now()
        )

    save_manifest(
        manifest_path,
        manifest,
    )

    return manifest


def publish_youtube(
    video_dir: Path,
    mode: str = "publish",
):
    ensure_publishing_enabled(mode)
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
            manifest.get(
                "description",
                "",
            ),
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

        error_text = str(exc)

        # -------------------------------------------------
        # YOUTUBE UPLOAD LIMIT
        # -------------------------------------------------

        if (
            "uploadLimitExceeded"
            in error_text
        ):

            update_platform_status(
                video_dir,
                "youtube",
                "upload_limit",
                error=(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            )

            print(
                "\n⚠️ YouTube upload limit reached."
            )

            print(
                "   Skipping YouTube upload."
            )

            return {
                "platform": "youtube",
                "status": "upload_limit",
                "post_id": None,
                "url": None,
            }

        # -------------------------------------------------
        # OTHER YOUTUBE FAILURE
        # -------------------------------------------------

        update_platform_status(
            video_dir,
            "youtube",
            "failed",
            error=(
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        )

        raise


def publish_instagram(
    video_dir: Path,
    mode: str = "publish",
):
    """
    Publish an Instagram Reel with checkpointing.

    The Instagram container ID is saved immediately after
    creation so an interrupted connection can resume without
    creating a duplicate container.
    """

    ensure_publishing_enabled(mode)

    manifest_path = video_dir / "manifest.json"

    manifest = initialize_social_manifest(
        video_dir
    )

    video_path = Path(
        manifest["video_path"]
    )

    caption = manifest.get(
        "description",
        "",
    )

    instagram = manifest["social"]["instagram"]

    # -----------------------------------------------------
    # ALREADY PUBLISHED
    # -----------------------------------------------------

    if instagram.get("status") == "published":
        print(
            "\n⏭️ Instagram already published."
        )

        return {
            "platform": "instagram",
            "media_id": instagram.get(
                "post_id"
            ),
            "video_url": instagram.get(
                "video_url"
            ),
            "status": "published",
        }

    try:

        # -------------------------------------------------
        # EXISTING CONTAINER
        # -------------------------------------------------

        container_id = instagram.get(
            "container_id"
        )

        if container_id:

            print(
                "\n[INSTAGRAM] Resuming existing "
                f"container: {container_id}"
            )

        # -------------------------------------------------
        # CREATE NEW CONTAINER
        # -------------------------------------------------

        else:

            video_url = get_public_video_url(
                video_path
            )

            print(
                "\n[INSTAGRAM] Publishing:"
                f"\n{video_url}"
            )

            container_id = create_reel_container(
                video_url,
                caption,
            )

            print(
                "[INSTAGRAM] Container created: "
                f"{container_id}"
            )

            # ---------------------------------------------
            # CRITICAL CHECKPOINT
            # ---------------------------------------------

            manifest = load_manifest(
                manifest_path
            )

            manifest["social"]["instagram"][
                "container_id"
            ] = container_id

            manifest["social"]["instagram"][
                "status"
            ] = "processing"

            manifest["social"]["instagram"][
                "error"
            ] = None

            save_manifest(
                manifest_path,
                manifest,
            )

            print(
                "[INSTAGRAM] Container ID "
                "checkpoint saved."
            )

        # -------------------------------------------------
        # WAIT FOR PROCESSING
        # -------------------------------------------------

        wait_for_processing(
            container_id
        )

        print(
            "[INSTAGRAM] Video processing complete."
        )

        # -------------------------------------------------
        # PUBLISH
        # -------------------------------------------------

        media_id = publish_container(
            container_id
        )

        print(
            "[INSTAGRAM] Published: "
            f"{media_id}"
        )

        # -------------------------------------------------
        # FINAL CHECKPOINT
        # -------------------------------------------------

        manifest = load_manifest(
            manifest_path
        )

        instagram = manifest[
            "social"
        ][
            "instagram"
        ]

        instagram["status"] = "published"
        instagram["post_id"] = media_id
        instagram["published_at"] = utc_now()
        instagram["error"] = None

        save_manifest(
            manifest_path,
            manifest,
        )

        return {
            "platform": "instagram",
            "media_id": media_id,
            "video_url": get_public_video_url(
                video_path
            ),
            "status": "published",
        }

    except Exception as exc:

        # -------------------------------------------------
        # PRESERVE CHECKPOINT
        # -------------------------------------------------

        manifest = load_manifest(
            manifest_path
        )

        instagram = manifest[
            "social"
        ][
            "instagram"
        ]

        instagram["status"] = "failed"
        instagram["error"] = (
            f"{type(exc).__name__}: {exc}"
        )

        save_manifest(
            manifest_path,
            manifest,
        )

        print(
            "\n⚠️ Instagram publish failed:"
        )

        print(
            f"   {type(exc).__name__}: {exc}"
        )

        raise