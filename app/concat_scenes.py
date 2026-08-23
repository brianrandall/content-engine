from pathlib import Path
import subprocess


def concatenate_scenes(
    scene_paths: list[Path],
    output_path: Path,
):
    """
    Concatenate rendered scene videos into one visual track.
    """

    if not scene_paths:
        raise RuntimeError(
            "No scene videos were provided."
        )

    concat_file = (
        output_path.parent
        / "concat.txt"
    )

    with concat_file.open(
        "w",
        encoding="utf-8",
    ) as f:

        for scene_path in scene_paths:
            f.write(
                f"file '{scene_path.resolve()}'\n"
            )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(output_path),
        ],
        check=True,
    )

    concat_file.unlink(
        missing_ok=True
    )

    return output_path