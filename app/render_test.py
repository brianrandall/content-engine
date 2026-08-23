from pathlib import Path

from captions import parse_srt, render_caption_frames


srt_path = Path("output/captions.srt")
frames_dir = Path("output/caption_frames")

captions = parse_srt(srt_path)

duration = 9

render_caption_frames(
    captions,
    duration,
    frames_dir,
)

print("Caption frames created.")