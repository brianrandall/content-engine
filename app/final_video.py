from pathlib import Path
import subprocess


def create_final_video(
    run_dir: Path,
):
    """
    Combine visual track, caption frames, and narration
    into the final short-form video.
    """

    visual_track = (
        run_dir / "visual_track.mp4"
    )

    audio = (
        run_dir / "voice.wav"
    )

    caption_frames = (
        run_dir / "caption_frames"
    )

    output = (
        run_dir / "final_short.mp4"
    )

    frame_count = len(
        list(
            caption_frames.glob(
                "frame_*.png"
            )
        )
    )

    if frame_count == 0:
        raise RuntimeError(
            "No caption frames found."
        )

    if not visual_track.exists():
        raise RuntimeError(
            "Visual track not found."
        )

    if not audio.exists():
        raise RuntimeError(
            "Audio file not found."
        )

    print(
        f"📝 Found {frame_count} caption frames."
    )

    print(
        "🎬 Combining visuals, captions, "
        "and audio..."
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",

            # Background video
            "-i",
            str(visual_track),

            # Caption PNG sequence
            "-framerate",
            "30",
            "-i",
            str(
                caption_frames
                / "frame_%06d.png"
            ),

            # Narration
            "-i",
            str(audio),

            # Overlay captions
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:format=auto[v]",

            "-map",
            "[v]",

            "-map",
            "2:a",

            "-c:v",
            "libx264",

            "-c:a",
            "aac",

            "-shortest",

            "-pix_fmt",
            "yuv420p",

            str(output),
        ],
        check=True,
    )

    print(
        f"✅ Final video created: {output}"
    )

    return output