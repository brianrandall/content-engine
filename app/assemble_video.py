import subprocess
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]

FRAMES_DIR = BASE_DIR / "output" / "caption_frames"
AUDIO_PATH = BASE_DIR / "output" / "voice.wav"
OUTPUT_PATH = BASE_DIR / "output" / "captioned_video.mp4"


subprocess.run(
    [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-i",
        str(FRAMES_DIR / "frame_%06d.png"),
        "-i",
        str(AUDIO_PATH),
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-shortest",
        "-pix_fmt",
        "yuv420p",
        str(OUTPUT_PATH),
    ],
    check=True,
)


print(f"Video created: {OUTPUT_PATH}")