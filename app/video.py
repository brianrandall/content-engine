from pathlib import Path
import re
import subprocess

import edge_tts


BASE_DIR = Path(__file__).resolve().parents[1]

VOICE = "en-US-AriaNeural"


def clean_for_tts(text: str) -> str:
    """
    Clean narration text before sending it to TTS.
    """

    text = text.strip()

    # Remove URLs.
    text = re.sub(
        r"https?://\S+",
        "",
        text,
    )

    text = re.sub(
        r"www\.\S+",
        "",
        text,
    )

    # Remove markdown emphasis.
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Remove markdown bullets.
    text = re.sub(
        r"(?m)^\s*[-•]\s*",
        "",
        text,
    )

    # Remove hashtags.
    text = re.sub(
        r"(?<!\w)#[A-Za-z0-9_]+",
        "",
        text,
    )

    # Remove bracketed production notes.
    text = re.sub(
        r"\[[^\]]*\]",
        "",
        text,
    )

    # Remove parenthetical production notes.
    text = re.sub(
        r"\([^)]*\)",
        "",
        text,
    )

    # Remove stray slash characters.
    text = re.sub(
        r"\s*/\s*",
        " ",
        text,
    )

    # Remove quotation marks.
    text = text.replace('"', "")
    text = text.replace("“", "")
    text = text.replace("”", "")
    text = text.replace("‘", "'")
    text = text.replace("’", "'")

    # Normalize whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def create_video(
    content: dict,
    job_dir: Path,
):
    """
    Generate narration and captions for one content package.
    """

    narration = content["narration"]

    cleaned_narration = clean_for_tts(
        narration
    )

    if not cleaned_narration:
        raise RuntimeError(
            "Narration is empty after cleaning."
        )

    audio_path = (
        job_dir / "voice.wav"
    )

    subtitle_path = (
        job_dir / "captions.srt"
    )

    print(
        f"🎙️ Voice: {audio_path}"
    )

    print(
        f"📝 Captions: {subtitle_path}"
    )

    # -----------------------------------------------------
    # Generate narration
    # -----------------------------------------------------

    communicate = edge_tts.Communicate(
        cleaned_narration,
        VOICE,
    )

    # Edge-TTS writes MP3 by default.
    temp_mp3 = (
        job_dir / "voice.mp3"
    )

    communicate.save_sync(
        str(temp_mp3)
    )

    # Convert to WAV for the rest of the pipeline.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(temp_mp3),
            "-ar",
            "44100",
            "-ac",
            "1",
            str(audio_path),
        ],
        check=True,
    )

    temp_mp3.unlink(
        missing_ok=True
    )

    # -----------------------------------------------------
    # Generate captions
    # -----------------------------------------------------

    subprocess.run(
        [
            "whisper",
            str(audio_path),
            "--model",
            "base",
            "--output_format",
            "srt",
            "--output_dir",
            str(job_dir),
        ],
        check=True,
    )

    whisper_output = (
        job_dir
        / "voice.srt"
    )

    if whisper_output.exists():
        whisper_output.replace(
            subtitle_path
        )

    if not subtitle_path.exists():
        raise RuntimeError(
            "Whisper did not create captions.srt."
        )

    return audio_path, subtitle_path