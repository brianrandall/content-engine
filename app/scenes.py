from pathlib import Path
import random
import subprocess


BASE_DIR = Path(__file__).resolve().parents[1]

WIDTH = 1080
HEIGHT = 1920
FPS = 30


# ---------------------------------------------------------
# RANDOM VISUAL EFFECTS
# ---------------------------------------------------------

EFFECTS = [
    "zoom_in",
    "zoom_out",
    "pan_left",
    "pan_right",
]


def create_scene(
    image_path: Path,
    output_path: Path,
    duration: float,
    previous_effect: str | None = None,
):
    """
    Turn a still image into a vertical video scene.

    A random motion effect is selected for each scene.
    The same effect will never be used twice in a row.
    """

    frames = max(
        int(round(duration * FPS)),
        1,
    )

    # -----------------------------------------------------
    # Choose an effect that differs from the previous scene.
    # -----------------------------------------------------

    available_effects = [
        effect
        for effect in EFFECTS
        if effect != previous_effect
    ]

    effect = random.choice(
        available_effects
    )

    print(
        f"   🎥 Effect: {effect}"
    )

    # -----------------------------------------------------
    # Build the motion effect.
    # -----------------------------------------------------

    if effect == "zoom_in":

        zoompan = (
            "zoompan="
            "z='min(zoom+0.0008,1.12)':"
            f"d={frames}:"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    elif effect == "zoom_out":

        zoompan = (
            "zoompan="
            "z='if(eq(on,1),1.12,max(zoom-0.0008,1.0))':"
            f"d={frames}:"
            "x='iw/2-(iw/zoom/2)':"
            "y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    elif effect == "pan_left":

        zoompan = (
            "zoompan="
            "z='1.08':"
            f"x='(iw-iw/zoom)*on/{max(frames - 1, 1)}':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    elif effect == "pan_right":

        zoompan = (
            "zoompan="
            "z='1.08':"
            f"x='(iw-iw/zoom)*(1-on/{max(frames - 1, 1)})':"
            "y='ih/2-(ih/zoom/2)':"
            f"d={frames}:"
            f"s={WIDTH}x{HEIGHT}:"
            f"fps={FPS}"
        )

    else:
        raise ValueError(
            f"Unknown scene effect: {effect}"
        )

    # -----------------------------------------------------
    # Prepare image and apply motion.
    # -----------------------------------------------------

    filter_chain = (
        f"scale={WIDTH}:{HEIGHT}:"
        "force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"{zoompan}"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(image_path),

            "-vf",
            filter_chain,

            "-frames:v",
            str(frames),

            "-c:v",
            "libx264",

            "-pix_fmt",
            "yuv420p",

            str(output_path),
        ],
        check=True,
    )

    return effect


# ---------------------------------------------------------
# VISUAL PLAN PARSER
# ---------------------------------------------------------


def parse_visual_plan(plan: str):
    scenes = []

    blocks = plan.split(
        "SCENE "
    )

    for block in blocks[1:]:

        lines = block.strip().splitlines()

        scene = {
            "visual": "",
            "search": "",
            "duration": 3.0,
        }

        for line in lines:

            line = line.strip()

            if line.startswith("VISUAL:"):

                scene["visual"] = line.replace(
                    "VISUAL:",
                    "",
                    1,
                ).strip()

            elif line.startswith("SEARCH:"):

                scene["search"] = line.replace(
                    "SEARCH:",
                    "",
                    1,
                ).strip()

            elif line.startswith("DURATION:"):

                duration_text = line.replace(
                    "DURATION:",
                    "",
                    1,
                ).strip()

                try:

                    scene["duration"] = float(
                        duration_text.split()[0]
                    )

                except ValueError:

                    scene["duration"] = 3.0

        scenes.append(scene)

    return scenes
