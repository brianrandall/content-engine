from pathlib import Path
from datetime import datetime
import re


BASE_DIR = Path(__file__).resolve().parents[1]
RUNS_DIR = BASE_DIR / "output" / "runs"


def slugify(text: str) -> str:
    """Convert text into a filesystem-safe slug."""

    text = text.lower()

    text = re.sub(
        r"[^a-z0-9]+",
        "_",
        text,
    )

    return text.strip("_")[:60]


def create_run(topic: str) -> Path:
    """
    Create a unique directory for an entire production run.
    """

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    slug = slugify(topic)

    run_dir = (
        RUNS_DIR
        / f"{timestamp}_{slug}"
    )

    run_dir.mkdir(
        parents=True,
        exist_ok=False,
    )

    return run_dir


def create_video_job(
    run_dir: Path,
    index: int,
    title: str,
) -> Path:
    """
    Create an isolated directory for one generated video.
    """

    job_dir = get_video_job(
        run_dir,
        index,
        title,
    )

    (job_dir / "scenes").mkdir(
        parents=True,
        exist_ok=True,
    )

    (job_dir / "assets").mkdir(
        parents=True,
        exist_ok=True,
    )

    (job_dir / "caption_frames").mkdir(
        parents=True,
        exist_ok=True,
    )

    return job_dir


def get_video_job(
    run_dir: Path,
    index: int,
    title: str,
) -> Path:
    """
    RETURN DIRECTORY OF EXISTING VIDEO JOB
    """

    slug = slugify(title)

    return (
        run_dir
        / f"{index:02d}_{slug}"
    )
