import os
import time
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

BASE_URL = (
    "https://graph.instagram.com/v23.0"
)

VIDEO_URL = (
    "https://brianmacm1.tail02ee1d.ts.net/"
    "runs/20260824_123421_xiaomi_cpu_matches_apple_s_single_threaded_performance_outpe/"
    "05_the_future_of_mobile_gaming_cpus/"
    "final_short.mp4"
)


# =========================================================
# VALIDATION
# =========================================================

if not ACCESS_TOKEN:
    raise RuntimeError(
        "INSTAGRAM_ACCESS_TOKEN is not set."
    )

if not IG_USER_ID:
    raise RuntimeError(
        "INSTAGRAM_USER_ID is not set."
    )


# =========================================================
# CREATE REEL CONTAINER
# =========================================================

print()
print("=" * 60)
print("INSTAGRAM REEL PUBLISH TEST")
print("=" * 60)
print()

print("Creating Reel media container...")

response = requests.post(
    f"{BASE_URL}/{IG_USER_ID}/media",
    params={
        "media_type": "REELS",
        "video_url": VIDEO_URL,
        "caption": (
            "A new story from Daily News Content. "
            "🔥"
        ),
        "access_token": ACCESS_TOKEN,
    },
    timeout=60,
)

print(
    f"HTTP {response.status_code}"
)

print(
    response.text
)

response.raise_for_status()

data = response.json()

container_id = data.get(
    "id"
)

if not container_id:
    raise RuntimeError(
        "Instagram did not return a container ID."
    )


print()
print(
    f"Container created: {container_id}"
)


# =========================================================
# WAIT FOR PROCESSING
# =========================================================

print()
print(
    "Waiting for Instagram to process video..."
)

for attempt in range(20):

    time.sleep(5)

    status_response = requests.get(
        f"{BASE_URL}/{container_id}",
        params={
            "fields": "status_code,status",
            "access_token": ACCESS_TOKEN,
        },
        timeout=30,
    )

    print(
        f"Attempt {attempt + 1}: "
        f"{status_response.text}"
    )

    status_response.raise_for_status()

    status = status_response.json()

    status_code = status.get(
        "status_code"
    )

    if status_code == "FINISHED":
        print()
        print(
            "Instagram finished processing "
            "the video."
        )
        break

    if status_code in (
        "ERROR",
        "EXPIRED",
    ):
        raise RuntimeError(
            "Instagram failed to process "
            f"the video: {status}"
        )

else:

    raise RuntimeError(
        "Timed out waiting for Instagram "
        "to process the video."
    )


# =========================================================
# PUBLISH
# =========================================================

print()
print(
    "Publishing Reel..."
)

publish_response = requests.post(
    f"{BASE_URL}/{IG_USER_ID}/media_publish",
    params={
        "creation_id": container_id,
        "access_token": ACCESS_TOKEN,
    },
    timeout=60,
)

print(
    f"HTTP {publish_response.status_code}"
)

print(
    publish_response.text
)

publish_response.raise_for_status()

published = publish_response.json()

media_id = published.get(
    "id"
)

print()
print("=" * 60)
print("🔥 INSTAGRAM REEL PUBLISHED")
print("=" * 60)
print()
print(
    f"Media ID: {media_id}"
)
print()
