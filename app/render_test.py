from pathlib import Path

from captions import parse_srt, render_caption_frames


def run_render_test():
    srt_path = Path("output/captions.srt")
    frames_dir = Path("output/caption_frames")
    captions = parse_srt(srt_path)
    render_caption_frames(captions, 9, frames_dir)
    print("Caption frames created.")


if __name__ == "__main__":
    run_render_test()