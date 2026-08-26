import os
import time
import requests

from dotenv import load_dotenv


def run_live_test():
    if os.getenv("CONTENT_ENGINE_LIVE_TESTS") != "1":
        raise RuntimeError(
            "Set CONTENT_ENGINE_LIVE_TESTS=1 to run live publishing tests."
        )

    load_dotenv()

    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.getenv("INSTAGRAM_USER_ID")

    if not access_token:
        raise RuntimeError("INSTAGRAM_ACCESS_TOKEN is not set.")

    if not ig_user_id:
        raise RuntimeError("INSTAGRAM_USER_ID is not set.")

    base_url = "https://graph.instagram.com/v23.0"
    video_url = (
        "https://brianmacm1.tail02ee1d.ts.net/"
        "runs/20260824_123421_xiaomi_cpu_matches_apple_s_single_threaded_performance_outpe/"
        "05_the_future_of_mobile_gaming_cpus/"
        "final_short.mp4"
    )

    print()
    print("=" * 60)
    print("INSTAGRAM REEL PUBLISH TEST")
    print("=" * 60)
    print()
    print("Creating Reel media container...")

    response = requests.post(
        f"{base_url}/{ig_user_id}/media",
        params={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": "A new story from Daily News Content. 🔥",
            "access_token": access_token,
        },
        timeout=60,
    )
    response.raise_for_status()
    container_id = response.json().get("id")

    if not container_id:
        raise RuntimeError("Instagram did not return a container ID.")

    print(f"Container created: {container_id}")
    print("Waiting for Instagram to process video...")

    for attempt in range(20):
        time.sleep(5)
        status_response = requests.get(
            f"{base_url}/{container_id}",
            params={
                "fields": "status_code,status",
                "access_token": access_token,
            },
            timeout=30,
        )
        status_response.raise_for_status()
        status = status_response.json()
        print(f"Attempt {attempt + 1}: {status}")

        if status.get("status_code") == "FINISHED":
            break

        if status.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(
                f"Instagram failed to process the video: {status}"
            )
    else:
        raise RuntimeError(
            "Timed out waiting for Instagram to process the video."
        )

    print("Publishing Reel...")
    publish_response = requests.post(
        f"{base_url}/{ig_user_id}/media_publish",
        params={
            "creation_id": container_id,
            "access_token": access_token,
        },
        timeout=60,
    )
    publish_response.raise_for_status()
    media_id = publish_response.json().get("id")
    print(f"Instagram Reel published. Media ID: {media_id}")


if __name__ == "__main__":
    run_live_test()
