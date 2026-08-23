from pathlib import Path

from research import generate_visual_plan
from scenes import parse_visual_plan, create_scene
from assets import get_image
from concat_scenes import concatenate_scenes


BASE_DIR = Path(__file__).resolve().parents[1]

ASSETS_DIR = BASE_DIR / "output" / "assets"
SCENES_DIR = BASE_DIR / "output" / "scenes"


def build_visual_track(topic: str, script: str):

    print("🧠 Creating visual plan...")

    plan = generate_visual_plan(
        topic,
        script,
    )

    scenes = parse_visual_plan(plan)

    if not scenes:
        raise RuntimeError(
            "Ollama did not return any scenes."
        )

    print(f"🎬 Found {len(scenes)} scenes.")

    scene_paths = []

    for index, scene in enumerate(scenes, 1):

        print(
            f"\n🎞️ Scene {index}: "
            f"{scene['search']}"
        )

        image_filename = (
            f"scene_{index:02d}.jpg"
        )

        image_path = get_image(
            scene["search"],
            image_filename,
        )

        scene_path = (
            SCENES_DIR /
            f"scene_{index:02d}.mp4"
        )

        print(
            f"🎥 Creating {scene['duration']}s scene..."
        )

        create_scene(
            image_path,
            scene_path,
            scene["duration"],
        )

        scene_paths.append(scene_path)

    print("\n🔗 Combining scenes...")

    visual_track = concatenate_scenes(
        scene_paths
    )

    print(
        f"\n✅ Visual track created:\n"
        f"{visual_track}"
    )

    return visual_track


if __name__ == "__main__":

    topic = "AI automation"

    script = """
AI can now automate a surprising amount of boring work.
The trick is knowing which tasks to give it.
Start with repetitive tasks that follow predictable steps.
"""

    build_visual_track(
        topic,
        script,
    )