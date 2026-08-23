import json
import subprocess
from pathlib import Path

from app.job import (
    create_run,
    create_video_job,
    get_video_job,
    slugify,
)

from app.research import (
    search_web,
    analyze_research,
    discover_topics,
    score_topic,
    generate_content,
    generate_visual_plan,
)

from app.scenes import (
    create_scene,
)

from app.assets import get_image
from app.concat_scenes import concatenate_scenes
from app.video import create_video
from app.captions import (
    parse_srt,
    render_caption_frames,
)
from app.final_video import create_final_video


# =========================================================
# PATHS
# =========================================================

BASE_DIR = Path(__file__).resolve().parents[1]

OUTPUT_DIR = BASE_DIR / "output"

# =========================================================
# HELPERS
# =========================================================

def get_audio_duration(
    audio_path: Path,
) -> float:
    """Return the exact duration of an audio file."""

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return float(
        result.stdout.strip()
    )


def normalize_scene_durations(
    scenes,
    total_duration: float,
):
    """
    Scale scene durations proportionally so their
    combined duration matches the narration duration.
    """

    if not scenes:
        raise RuntimeError(
            "No visual scenes were generated."
        )

    requested_total = sum(
        scene["duration"]
        for scene in scenes
    )

    if requested_total <= 0:

        equal_duration = (
            total_duration
            / len(scenes)
        )

        for scene in scenes:
            scene["duration"] = (
                equal_duration
            )

        return scenes

    scale = (
        total_duration
        / requested_total
    )

    for scene in scenes:
        scene["duration"] *= scale

    return scenes


# =========================================================
# SINGLE VIDEO
# =========================================================

def create_content_video(
    content: dict,
    topic: str,
    research: dict,
    run_dir: Path,
    index: int,
):
    """
    Generate one complete video from one content package.
    """

    title = content["title"]

    video_dir = create_video_job(
        run_dir,
        index,
        title,
    )

    assets_dir = video_dir / "assets"

    video_manifest = {
        "index": index,
        "title": title,
        "angle": content["angle"],
        "hook": content["hook"],
        "narration": content["narration"],
        "description": content["description"],
        "cta": content["cta"],
        "video_path": None,
        "audio_path": None,
        "captions_path": None,
        "visual_plan_path": None,
        "research_path": str(
            video_dir / "research.json"
        ),
    }

    research_path = video_dir / "research.json"

    with open(
        research_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            research,
            f,
            indent=2,
            ensure_ascii=False,
        )

    scenes_dir = (
        video_dir / "scenes"
    )

    caption_frames_dir = (
        video_dir
        / "caption_frames"
    )

    scenes_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print(
        "\n"
        "================================"
    )

    print(
        f"🎬 VIDEO {index}: {title}"
    )

    print(
        f"📁 {video_dir}"
    )

    print(
        "================================"
    )


    audio_path = video_dir / "voice.wav"
    captions_path = video_dir / "captions.srt"

    # -----------------------------------------------------
    # VOICE + CAPTIONS
    # -----------------------------------------------------

    if not audio_path.exists():
        print(
            "\n🎙️ Generating narration..."
        )
        create_video(
            content,
            video_dir,
        )
    else:
        print(
            "\n⏭️ Narration already exists."
        )

    if not captions_path.exists():
        print(
            "\n📝 Generating captions..."
        )
        subprocess.run(
            [
                "whisper",
                str(audio_path),
                "--model",
                "base",
                "--output_format",
                "srt",
                "--output_dir",
                str(video_dir),
            ],
            check=True,
        )
    else:
        print(
            "\n⏭️ Captions already exist."
        )

    # -----------------------------------------------------
    # AUDIO DURATION
    # -----------------------------------------------------

    duration = get_audio_duration(
        audio_path
    )

    print(
        f"⏱️ Narration: "
        f"{duration:.2f}s"
    )

    # -----------------------------------------------------
    # CAPTION FRAMES
    # -----------------------------------------------------

    caption_frames_complete = (
        caption_frames_dir
        / ".complete"
    )

    if caption_frames_complete.exists():

        print(
            "\n⏭️ Caption frames already exist."
        )

    else:

        print(
            "\n📝 Rendering caption frames..."
        )

        captions = parse_srt(
            captions_path
        )

        render_caption_frames(
            captions,
            duration,
            caption_frames_dir,
        )

        caption_frames_complete.touch()

    # -----------------------------------------------------
    # VISUAL PLAN
    # -----------------------------------------------------

    visual_plan_path = (
        video_dir / "visual_plan.json"
    )

    if visual_plan_path.exists():

        print(
            "\n⏭️ Visual plan already exists."
        )

        with open(
            visual_plan_path,
            "r",
            encoding="utf-8",
        ) as f:

            visual_plan = json.load(f)

    else:

        print(
            "\n🎬 Creating visual plan..."
        )

        visual_plan = generate_visual_plan(
            topic,
            content["narration"],
        )

        # Save the visual plan so we can inspect it later.

        with open(
            visual_plan_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                visual_plan,
                f,
                indent=2,
            )

    scenes = visual_plan["scenes"]

    print(
        f"Found {len(scenes)} "
        "visual scenes."
    )

    if not scenes:
        raise RuntimeError(
            "Visual planner returned no scenes."
        )

    # -----------------------------------------------------
    # VISUAL ASSETS
    # -----------------------------------------------------

    print(
        "\n🖼️ Gathering visuals..."
    )

    successful_scenes = []

    for scene_index, scene in enumerate(
        scenes,
        1,
    ):

        image_filename = (
            f"scene_{scene_index:02d}.jpg"
        )

        image_path = (
            assets_dir / image_filename
        )

        print(
            f"\n🎞️ Scene {scene_index}: "
            f"{scene['search']}"
        )

        if image_path.exists():
            print(
                "   ⏭️ Image already exists."
            )
        else:
            print(
                "   🖼️ Downloading image..."
            )

            image_path = get_image(
                scene["search"],
                image_filename,
                output_dir=assets_dir,
            )

        if image_path is None:
            print(
                f"   ~~~ Skipping scene "
                f"{scene_index}"
            )
            continue

        successful_scenes.append(
            {
                "image_path": image_path,
                "scene": scene,
            }
        )

    if not successful_scenes:
        raise RuntimeError(
            "No usable visual assets "
            "were found."
        )

    # -----------------------------------------------------
    # NORMALIZE TIMING
    # -----------------------------------------------------

    print(
        "\n⏱️ Normalizing visual timing..."
    )

    successful_scene_data = [
        item["scene"]
        for item in successful_scenes
    ]

    normalize_scene_durations(
        successful_scene_data,
        duration,
    )

    for scene_index, item in enumerate(
        successful_scenes,
        1,
    ):

        print(
            f"   Scene {scene_index}: "
            f"{item['scene']['duration']:.2f}s"
        )

    # -----------------------------------------------------
    # RENDER SCENES
    # -----------------------------------------------------


    print(
        "\n🎬 Rendering scenes..."
    )

    scene_paths = []

    previous_effect = None

    for scene_index, item in enumerate(
        successful_scenes,
        1,
    ):

        scene = item["scene"]

        scene_path = (
            scenes_dir
            / f"scene_{scene_index:02d}.mp4"
        )

        scene_metadata_path = (
            scenes_dir
            / f"scene_{scene_index:02d}.json"
        )

        # -------------------------------------------------
        # RESUME EXISTING SCENE
        # -------------------------------------------------

        if (
            scene_path.exists()
            and scene_metadata_path.exists()
        ):

            print(
                f"\n⏭️ Scene {scene_index} "
                "already exists."
            )

            with open(
                scene_metadata_path,
                "r",
                encoding="utf-8",
            ) as f:

                scene_metadata = json.load(f)

            previous_effect = scene_metadata[
                "effect"
            ]

            scene_paths.append(
                scene_path
            )

            continue

        # -------------------------------------------------
        # RENDER NEW SCENE
        # -------------------------------------------------

        previous_effect = create_scene(
            item["image_path"],
            scene_path,
            scene["duration"],
            previous_effect,
        )

        # -------------------------------------------------
        # SAVE SCENE METADATA
        # -------------------------------------------------

        with open(
            scene_metadata_path,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                {
                    "effect": previous_effect,
                    "duration": scene["duration"],
                    "image_path": str(
                        item["image_path"]
                    ),
                },
                f,
                indent=2,
                ensure_ascii=False,
            )

        scene_paths.append(
            scene_path
        )

    # -----------------------------------------------------
    # VISUAL TRACK
    # -----------------------------------------------------

    visual_track = (
        video_dir
        / "visual_track.mp4"
    )

    if visual_track.exists():

        print(
            "\n⏭️ Visual track already exists."
        )

    else:

        print(
            "\n🎞️ Building visual track..."
        )

        concatenate_scenes(
            scene_paths,
            visual_track,
        )

    # -----------------------------------------------------
    # FINAL VIDEO
    # -----------------------------------------------------

    final_video = (
        video_dir
        / "final_short.mp4"
    )

    if final_video.exists():

        print(
            "\n⏭️ Final video already exists."
        )
    else:

        print(
            "\n🔥 Creating final video..."
        )

        final_video = create_final_video(
            video_dir
        )

    video_manifest["video_path"] = str(
        final_video
    )

    video_manifest["audio_path"] = str(
        audio_path
    )

    video_manifest["captions_path"] = str(
        video_dir / "captions.srt"
    )

    video_manifest["visual_plan_path"] = str(
        video_dir / "visual_plan.json"
    )

    with open(
        video_dir / "manifest.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            video_manifest,
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"\n✅ VIDEO {index} COMPLETE"
    )

    return final_video


# =========================================================
# BATCH PIPELINE
# =========================================================




def run_pipeline(
    niche: str,
    content_count: int = 5,
):

    print(
        "\n"
        "================================"
    )

    print(
        "🚀 CONTENT ENGINE"
    )

    print(
        "================================"
    )

    print(
        f"Niche: {niche}"
    )

    print(
        f"Videos: {content_count}"
    )

    # -----------------------------------------------------
    # CREATE RUN
    # -----------------------------------------------------

    run_dir = create_run(niche)

    print(
        f"\n📁 Production run:"
    )

    print(
        f"   {run_dir}"
    )

    # -----------------------------------------------------
    # TOPIC DISCOVERY
    # -----------------------------------------------------

    print(
        "\n🧠 STEP 1 — Discovering topic opportunities..."
    )

    candidates = discover_topics(
        niche,
        count=10,
    )

    scored_topics = []

    for index, candidate in enumerate(
        candidates,
        1,
    ):

        print(
            f"\n🔎 Evaluating topic "
            f"{index}/{len(candidates)}: "
            f"{candidate['topic']}"
        )

        results = search_web(
            candidate["search_query"],
            max_results=5,
        )

        if not results:
            print(
                "   ⚠️ No research results. Skipping."
            )
            continue

        research = analyze_research(
            candidate["topic"],
            results,
        )

        score = score_topic(
            niche,
            candidate,
            research,
        )

        score["research"] = research

        scored_topics.append(
            score
        )

        print(
            f"   ⭐ Score: "
            f"{score['overall_score']}/10"
        )

    if not scored_topics:
        raise RuntimeError(
            "No viable topic opportunities found."
        )

    scored_topics.sort(
        key=lambda item: item["overall_score"],
        reverse=True,
    )

    selected_topic = scored_topics[0]

    topic = selected_topic["topic"]
    research = selected_topic["research"]

    print(
        "\n🏆 SELECTED TOPIC"
    )

    print(
        f"   {topic}"
    )

    print(
        f"   Score: "
        f"{selected_topic['overall_score']}/10"
    )

    print(
        f"   {selected_topic['reason']}"
    )

    with open(
        run_dir / "topic_opportunities.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            scored_topics,
            f,
            indent=4,
            ensure_ascii=False,
        )

    with open(
        run_dir / "selected_topic.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            selected_topic,
            f,
            indent=4,
            ensure_ascii=False,
        )

    # -----------------------------------------------------
    # RESEARCH SELECTED TOPIC
    # -----------------------------------------------------

    print(
        "\n🧠 STEP 2 — Researching selected topic..."
    )

    results = search_web(
        selected_topic["search_query"]
    )

    if not results:
        raise RuntimeError(
            "No research results found."
        )

    research = analyze_research(
        topic,
        results,
    )

    with open(
        run_dir / "research.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            research,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # -----------------------------------------------------
    # CONTENT GENERATION
    # -----------------------------------------------------

    print(
        "\n✍️ STEP 3 — Generating "
        f"{content_count} content packages..."
    )

    content_packages = generate_content(
        topic,
        research,
        count=content_count,
    )

    print(
        f"Generated "
        f"{len(content_packages)} packages."
    )

    # Save the exact generated JSON.

    with open(
        run_dir / "content.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            content_packages,
            f,
            indent=4,
            ensure_ascii=False,
        )

    # -----------------------------------------------------
    # GENERATE VIDEOS
    # -----------------------------------------------------

    completed_videos = []

    for index, content in enumerate(
        content_packages,
        1,
    ):

        try:

            final_video = (
                create_content_video(
                    content,
                    topic,
                    research,
                    run_dir,
                    index,
                )
            )

            completed_videos.append(
                final_video
            )

        except Exception as exc:

            print(
                "\n❌ VIDEO FAILED"
            )

            print(
                f"Video {index}: "
                f"{content['title']}"
            )

            print(
                f"Error: {exc}"
            )

    # -----------------------------------------------------
    # RUN MANIFEST
    # -----------------------------------------------------

    run_manifest = {
        "niche": niche,
        "selected_topic": topic,
        "content_count": content_count,
        "generated_count": len(content_packages),
        "completed_count": len(completed_videos),
        "topic_opportunities": str(
            run_dir / "topic_opportunities.json"
        ),
        "selected_topic_path": str(
            run_dir / "selected_topic.json"
        ),
        "research_path": str(
            run_dir / "research.json"
        ),
        "content_path": str(
            run_dir / "content.json"
        ),
        "videos": [
            str(video)
            for video in completed_videos
        ],
    }

    with open(
        run_dir / "manifest.json",
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            run_manifest,
            f,
            indent=2,
            ensure_ascii=False,
        )

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    print(
        "\n"
        "================================"
    )

    print(
        "🔥 PRODUCTION RUN COMPLETE"
    )

    print(
        "================================"
    )

    print(
        f"Created: "
        f"{len(completed_videos)}"
        f"/{len(content_packages)} videos"
    )

    print(
        f"\n📁 Run directory:"
    )

    print(
        run_dir
    )

    for video in completed_videos:

        print(
            f"\n🎬 {video}"
        )

    return completed_videos


# =========================================================
# ENTRY POINT
# =========================================================

def resume_run(run_dir: Path):
    """
    Resume incomplete videos from an existing production run.
    """

    print(
        "\n================================"
    )
    print(
        "🔄 RESUMING PRODUCTION RUN"
    )
    print(
        "================================"
    )

    content_path = run_dir / "content.json"
    research_path = run_dir / "research.json"

    if not content_path.exists():
        raise RuntimeError(
            f"Missing content.json in {run_dir}"
        )

    if not research_path.exists():
        raise RuntimeError(
            f"Missing research.json in {run_dir}"
        )

    with open(
        content_path,
        "r",
        encoding="utf-8",
    ) as f:
        content_packages = json.load(f)

    with open(
        research_path,
        "r",
        encoding="utf-8",
    ) as f:
        research = json.load(f)

    selected_topic_path = (
        run_dir / "selected_topic.json"
    )

    if selected_topic_path.exists():

        with open(
            selected_topic_path,
            "r",
            encoding="utf-8",
        ) as f:
            selected_topic = json.load(f)

        topic = selected_topic["topic"]

    else:
        raise RuntimeError(
            "Missing selected_topic.json."
        )

    completed_videos = []

    for index, content in enumerate(
        content_packages,
        1,
    ):

        video_dir = get_video_job(
        run_dir,
        index,
        content["title"],
        )

        final_video = (
            video_dir
            / "final_short.mp4"
        )

        if final_video.exists():

            print(
                f"\n✅ Video {index} already complete:"
            )

            print(
                f"   {content['title']}"
            )

            completed_videos.append(
                final_video
            )

            continue

        print(
            f"\n▶️ Resuming video {index}: "
            f"{content['title']}"
        )

        try:

            final_video = create_content_video(
                content,
                topic,
                research,
                run_dir,
                index,
            )

            completed_videos.append(
                final_video
            )

        except Exception as exc:

            print(
                "\n❌ VIDEO FAILED"
            )

            print(
                f"Video {index}: "
                f"{content['title']}"
            )

            print(
                f"Error: {exc}"
            )

    print(
        "\n================================"
    )

    print(
        "🔥 RESUME COMPLETE"
    )

    print(
        "================================"
    )

    print(
        f"Created/available: "
        f"{len(completed_videos)}"
        f"/{len(content_packages)} videos"
    )

    return completed_videos

if __name__ == "__main__":

    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "--resume":

        resume_run(
            Path(sys.argv[2]).expanduser()
        )

    else:

        niche = (
            sys.argv[1]
            if len(sys.argv) > 1
            else "AI automation"
        )

        run_pipeline(
            niche,
            content_count=5,
        )