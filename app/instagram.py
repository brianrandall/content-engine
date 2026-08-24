import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

ACCESS_TOKEN = os.getenv(
    "INSTAGRAM_ACCESS_TOKEN"
)

IG_USER_ID = os.getenv(
    "INSTAGRAM_USER_ID"
)

PUBLIC_BASE_URL = os.getenv(
    "MEDIA_PUBLIC_BASE_URL",
    "https://brianmacm1.tail02ee1d.ts.net",
)

GRAPH_VERSION = "v23.0"

BASE_URL = (
    f"https://graph.instagram.com/{GRAPH_VERSION}"
)


# =========================================================
# VALIDATION
# =========================================================

def _validate_config():

    if not ACCESS_TOKEN:
        raise RuntimeError(
            "INSTAGRAM_ACCESS_TOKEN is not set."
        )

    if not IG_USER_ID:
        raise RuntimeError(
            "INSTAGRAM_USER_ID is not set."
        )


# =========================================================
# ACCOUNT
# =========================================================

def get_account():

    _validate_config()

    response = requests.get(
        f"{BASE_URL}/me",
        params={
            "fields": "user_id,username,id",
            "access_token": ACCESS_TOKEN,
        },
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# MEDIA URL
# =========================================================

def get_public_video_url(
    video_path,
):
    """
    Convert a local output path into the
    public URL served by Tailscale Funnel.
    """

    video_path = Path(
        video_path
    ).resolve()

    output_dir = (
        Path(__file__).resolve().parents[1]
        / "output"
    ).resolve()

    try:

        relative_path = (
            video_path.relative_to(
                output_dir
            )
        )

    except ValueError:

        raise ValueError(
            f"Video is outside output directory: "
            f"{video_path}"
        )

    return (
        f"{PUBLIC_BASE_URL.rstrip('/')}/"
        f"{relative_path.as_posix()}"
    )


# =========================================================
# CREATE REEL
# =========================================================

def create_reel_container(
    video_url,
    caption="",
):

    _validate_config()

    response = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media",
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        },
        timeout=60,
    )

    if not response.ok:
        print()
        print("=" * 60)
        print("INSTAGRAM API ERROR")
        print()
        print(f"HTTP {response.status_code}")
        print(response.text)
        print("=" * 60)
        print()

        raise RuntimeError(
            f"Instagram API error "
            f"{response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    container_id = data.get(
        "id"
    )

    if not container_id:

        raise RuntimeError(
            "Instagram did not return "
            "a container ID."
        )

    return container_id


# =========================================================
# WAIT FOR PROCESSING
# =========================================================

def wait_for_processing(
    container_id,
    max_attempts=30,
    interval=5,
):

    for attempt in range(
        max_attempts
    ):

        time.sleep(
            interval
        )

        response = requests.get(
            f"{BASE_URL}/{container_id}",
            params={
                "fields": (
                    "status_code,status"
                ),
                "access_token": ACCESS_TOKEN,
            },
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        status_code = data.get(
            "status_code"
        )

        if status_code == "FINISHED":
            return data

        if status_code in (
            "ERROR",
            "EXPIRED",
        ):

            raise RuntimeError(
                "Instagram media processing "
                f"failed: {data}"
            )

    raise TimeoutError(
        "Instagram media processing "
        "timed out."
    )


# =========================================================
# PUBLISH
# =========================================================

def publish_container(
    container_id,
):

    _validate_config()

    response = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish",
        params={
            "creation_id": container_id,
            "access_token": ACCESS_TOKEN,
        },
        timeout=60,
    )

    if not response.ok:
        print()
        print("=" * 60)
        print("INSTAGRAM API ERROR")
        print()
        print(f"HTTP {response.status_code}")
        print(response.text)
        print("=" * 60)
        print()

        raise RuntimeError(
            f"Instagram API error "
            f"{response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    media_id = data.get(
        "id"
    )

    if not media_id:

        raise RuntimeError(
            "Instagram did not return "
            "a published media ID."
        )

    return media_id


# =========================================================
# COMPLETE PUBLISH FLOW
# =========================================================

def publish_reel(
    video_path,
    caption="",
):

    video_url = get_public_video_url(
        video_path
    )

    print(
        f"[INSTAGRAM] Publishing:"
        f"\n{video_url}"
    )

    container_id = create_reel_container(
        video_url,
        caption,
    )

    print(
        f"[INSTAGRAM] Container created: "
        f"{container_id}"
    )

    wait_for_processing(
        container_id
    )

    print(
        "[INSTAGRAM] Video processing complete."
    )

    media_id = publish_container(
        container_id
    )

    print(
        f"[INSTAGRAM] Published: "
        f"{media_id}"
    )

    return {
        "platform": "instagram",
        "media_id": media_id,
        "video_url": video_url,
        "status": "published",
    }


# =========================================================
# TEST
# =========================================================

if __name__ == "__main__":

    account = get_account()

    print(
        "Instagram account:"
    )

    print(
        account
    )
