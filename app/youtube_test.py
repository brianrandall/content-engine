from pathlib import Path

from app.youtube import upload_video


VIDEO_PATH = Path(
    "/Users/brianrandall/Dropbox/PROJECTS/content-engine/"
    "output/runs/20260823_211340_spooky_stories_for_kids/"
    "01_the_1923_story_behind_haunted_dolls/"
    "final_short.mp4"
)


def run_live_test():
    import os

    if os.getenv("CONTENT_ENGINE_LIVE_TESTS") != "1":
        raise RuntimeError(
            "Set CONTENT_ENGINE_LIVE_TESTS=1 to run live publishing tests."
        )

    result = upload_video(
        video_path=VIDEO_PATH,
        title="TEST — The 1923 Story Behind Haunted Dolls",
        description="Private test upload from Content Engine.",
    )

    print()
    print("================================")
    print("YOUTUBE UPLOAD SUCCESS")
    print("================================")
    print(f"Video ID: {result['post_id']}")
    print(f"URL:      {result['url']}")


if __name__ == "__main__":
    run_live_test()