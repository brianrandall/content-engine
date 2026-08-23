from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "output"

WIDTH = 1080
HEIGHT = 1920

# Caption tuning
MIN_WORDS = 3
MAX_WORDS = 7

# Small timing cushion so captions don't switch quite so early.
TIMING_BUFFER = 0.10


def timestamp_to_seconds(timestamp: str) -> float:
    hours, minutes, rest = timestamp.split(":")
    seconds, milliseconds = rest.split(",")

    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000
    )


def parse_srt(srt_path: Path):
    captions = []

    text = srt_path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")

    for block in blocks:
        lines = block.splitlines()

        if len(lines) < 3:
            continue

        start, end = lines[1].split(" --> ")
        caption_text = " ".join(lines[2:]).strip()

        captions.append(
            {
                "start": timestamp_to_seconds(start),
                "end": timestamp_to_seconds(end),
                "text": caption_text,
            }
        )

    return captions


def split_caption_text(text: str):
    """
    Break a sentence-sized caption into shorter,
    natural-looking caption chunks.

    Target:
        3-7 words per chunk.

    Prefer breaking around punctuation and avoid
    tiny orphan chunks.
    """

    words = text.split()

    if len(words) <= MAX_WORDS:
        return [text]

    chunks = []
    current = []

    for word in words:
        current.append(word)

        word_count = len(current)

        # Strong punctuation makes a natural break.
        punctuation_break = word.endswith(
            (",", ";", ":", "?", "!")
        )

        # Periods are especially strong breaks.
        sentence_break = word.endswith(".")

        # If we're at the ideal range, break naturally.
        if word_count >= MIN_WORDS:

            if sentence_break:
                chunks.append(" ".join(current))
                current = []

            elif punctuation_break:
                chunks.append(" ".join(current))
                current = []

            elif word_count >= MAX_WORDS:
                chunks.append(" ".join(current))
                current = []

    if current:
        # Don't leave a tiny orphan chunk.
        if (
            chunks
            and len(current) < MIN_WORDS
        ):
            chunks[-1] += " " + " ".join(current)
        else:
            chunks.append(" ".join(current))

    return chunks


def build_caption_chunks(captions):
    """
    Convert sentence-level captions into shorter chunks.

    Each original sentence's time range is divided
    proportionally according to word count.
    """

    chunks = []

    for caption in captions:

        text = caption["text"].strip()

        if not text:
            continue

        start = caption["start"]
        end = caption["end"]

        duration = end - start

        words = text.split()

        if not words:
            continue

        text_chunks = split_caption_text(text)

        total_words = len(words)

        current_time = start

        for index, chunk_text in enumerate(text_chunks):

            chunk_words = len(chunk_text.split())

            # Allocate time according to word count.
            chunk_duration = (
                duration
                * chunk_words
                / total_words
            )

            chunk_start = current_time

            chunk_end = current_time + chunk_duration

            # Give the next caption a tiny amount of
            # hesitation so it doesn't jump early.
            if index > 0:
                chunk_start = min(
                    chunk_start + TIMING_BUFFER,
                    end,
                )

            # Never let the final chunk run past
            # the original sentence boundary.
            if index == len(text_chunks) - 1:
                chunk_end = end

            chunks.append(
                {
                    "start": chunk_start,
                    "end": chunk_end,
                    "text": chunk_text,
                }
            )

            current_time += chunk_duration

    return chunks


def create_caption_image(text: str) -> Image.Image:
    image = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 0),
    )

    draw = ImageDraw.Draw(image)

    font = ImageFont.truetype(
        "/System/Library/Fonts/Helvetica.ttc",
        64,
    )

    max_width = 900

    words = text.split()
    lines = []
    current_line = ""

    for word in words:

        test_line = (
            f"{current_line} {word}"
        ).strip()

        bbox = draw.textbbox(
            (0, 0),
            test_line,
            font=font,
        )

        if bbox[2] - bbox[0] <= max_width:
            current_line = test_line

        else:

            if current_line:
                lines.append(current_line)

            current_line = word

    if current_line:
        lines.append(current_line)

    line_height = 80
    total_height = len(lines) * line_height

    y = (HEIGHT - total_height) / 2

    for line in lines:

        bbox = draw.textbbox(
            (0, 0),
            line,
            font=font,
        )

        text_width = bbox[2] - bbox[0]

        x = (WIDTH - text_width) / 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill="white",
            stroke_width=5,
            stroke_fill="black",
        )

        y += line_height

    return image


def render_caption_frames(
    captions,
    duration: float,
    output_dir: Path,
    fps: int = 30,
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------
    # Remove caption frames from previous renders.
    # --------------------------------------------------

    for old_frame in output_dir.glob(
        "frame_*.png"
    ):
        old_frame.unlink()

    # --------------------------------------------------
    # Convert sentence captions into short chunks.
    # --------------------------------------------------

    caption_chunks = build_caption_chunks(
        captions
    )

    print(
        f"📝 Created {len(caption_chunks)} "
        f"caption chunks."
    )

    # --------------------------------------------------
    # Render one transparent PNG per video frame.
    # --------------------------------------------------

    frame_count = int(
        duration * fps
    )

    for frame_number in range(
        frame_count
    ):

        current_time = (
            frame_number / fps
        )

        active_caption = None

        for caption in caption_chunks:

            if (
                caption["start"]
                <= current_time
                < caption["end"]
            ):
                active_caption = caption
                break

        if active_caption:

            image = create_caption_image(
                active_caption["text"]
            )

        else:

            image = Image.new(
                "RGBA",
                (WIDTH, HEIGHT),
                (0, 0, 0, 0),
            )

        frame_path = (
            output_dir
            / f"frame_{frame_number:06d}.png"
        )

        image.save(frame_path)