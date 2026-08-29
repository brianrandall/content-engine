from pathlib import Path
import json
import re

import requests
from ddgs import DDGS
from ddgs.exceptions import DDGSException


BASE_DIR = Path(__file__).resolve().parents[1]

ASSETS_DIR = BASE_DIR / "output" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


BLOCKED_DOMAINS = [
    "pinterest.com",
    "pinimg.com",
]

# Tiny HTTP error pages, tracking pixels, and placeholder responses can
# sometimes arrive with a 200 status. Anything smaller than this is not
# useful as a production visual and should be rejected before FFmpeg sees it.
MIN_IMAGE_BYTES = 2048


def clean_search_query(query: str) -> str:
    """
    Clean an LLM-generated visual search query.

    The model sometimes produces overly specific queries containing
    quotes or other punctuation that can cause DDGS to fail.
    """

    query = query.strip()

    # Remove surrounding quotation marks.
    query = query.replace('"', "")
    query = query.replace("'", "")

    # Remove common LLM punctuation.
    query = re.sub(r"[*\[\]{}]", "", query)

    # Collapse repeated whitespace.
    query = re.sub(r"\s+", " ", query)

    return query.strip()


def _detect_image_format(content: bytes) -> str | None:
    """Identify common raster-image formats from their file signatures."""

    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    if (
        len(content) >= 12
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP"
    ):
        return "webp"

    # AVIF/HEIF-family files use an ISO BMFF ftyp box. FFmpeg can usually
    # decode these even when the output filename happens to end in .jpg.
    if len(content) >= 12 and content[4:8] == b"ftyp":
        brand = content[8:12]
        if brand in {
            b"avif",
            b"avis",
            b"heic",
            b"heix",
            b"hevc",
            b"hevx",
            b"mif1",
            b"msf1",
        }:
            return "avif/heif"

    return None


def _validate_image_response(response: requests.Response) -> str:
    """
    Validate that a successful HTTP response is really usable image data.

    A 200 response is not enough: some hosts return HTML/error bodies or tiny
    placeholders while still reporting success. Reject those here so get_image
    can automatically continue to the next search result.
    """

    content = response.content
    content_type = response.headers.get("Content-Type", "")
    normalized_type = content_type.split(";", 1)[0].strip().lower()

    if not content:
        raise requests.RequestException("Downloaded image was empty.")

    if len(content) < MIN_IMAGE_BYTES:
        raise requests.RequestException(
            f"Downloaded image was only {len(content)} bytes; "
            f"minimum is {MIN_IMAGE_BYTES}."
        )

    if normalized_type and not normalized_type.startswith("image/"):
        raise requests.RequestException(
            f"Response Content-Type was not an image: {normalized_type}"
        )

    image_format = _detect_image_format(content)
    if image_format is None:
        preview = content[:80].lstrip().lower()

        if preview.startswith((b"<html", b"<!doctype html", b"<?xml")):
            raise requests.RequestException(
                "Image URL returned HTML/XML instead of image data."
            )

        raise requests.RequestException(
            "Downloaded bytes did not match a supported image signature."
        )

    return image_format


def search_images(query: str, max_results: int = 12):
    """
    Search for images while filtering known problematic domains.

    Returns an empty list instead of crashing if DDGS fails.
    """

    query = query.replace('"', "").replace("'", "").strip()

    results = []

    cleaned_query = clean_search_query(query)

    try:
        with DDGS() as ddgs:
            image_results = ddgs.images(
                cleaned_query,
                max_results=max_results,
            )

    except DDGSException as error:
        print(
            f"   ⚠️ Image search failed for: {cleaned_query}"
        )
        print(
            f"   ⚠️ DDGS error: {error}"
        )

        return []

    except Exception as error:
        print(
            f"   ⚠️ Unexpected image search error: {error}"
        )

        return []

    for result in image_results:
        image_url = result.get("image")
        source_url = result.get("url")

        if not image_url:
            continue

        combined_url = (
            f"{image_url} {source_url or ''}"
        ).lower()

        if any(
            domain in combined_url
            for domain in BLOCKED_DOMAINS
        ):
            continue

        results.append(
            {
                "title": result.get("title"),
                "url": image_url,
                "source": source_url,
            }
        )

    return results


def download_image(
    url: str,
    filename: str,
    output_dir: Path = ASSETS_DIR,
    source_url: str | None = None,
    title: str | None = None,
):
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = output_dir / filename

    response = requests.get(
        url,
        timeout=20,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0 Safari/537.36"
            ),
            "Accept": (
                "image/avif,image/webp,image/apng,"
                "image/svg+xml,image/*,*/*;q=0.8"
            ),
        },
    )

    response.raise_for_status()

    image_format = _validate_image_response(response)

    # Only write the file after validation succeeds. This prevents a failed
    # candidate from leaving a bogus .jpg behind for the renderer.
    output_path.write_bytes(response.content)

    metadata_path = output_path.with_suffix(".json")

    metadata = {
        "filename": filename,
        "image_url": url,
        "source_url": source_url,
        "title": title,
        "content_type": response.headers.get("Content-Type"),
        "detected_format": image_format,
        "bytes": len(response.content),
    }

    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    return output_path


def get_image(
    query: str,
    filename: str,
    output_dir: Path = ASSETS_DIR,
):
    """
    Find and download the first usable image.

    Search failures, invalid HTTP image responses, and individual download
    failures do not crash the pipeline. Bad candidates are skipped and the
    next search result is tried automatically.
    """

    cleaned_query = clean_search_query(query)

    results = search_images(cleaned_query)

    if not results:
        print(
            f"   ⚠️ No usable search results for: "
            f"{cleaned_query}"
        )

        return None

    errors = []

    for index, result in enumerate(results, 1):

        print(
            f"   Trying image {index}/{len(results)}..."
        )

        try:
            image_path = download_image(
                result["url"],
                filename,
                output_dir=output_dir,
                source_url=result.get("source"),
                title=result.get("title"),
            )

            print(
                f"   ✅ Image {index} validated and saved: "
                f"{image_path.name}"
            )

            return image_path

        except requests.RequestException as error:

            print(
                f"   ⚠️ Image {index} rejected: {error}"
            )

            errors.append(
                f"{result['url']}: {error}"
            )

        except Exception as error:

            print(
                f"   ⚠️ Unexpected image error: {error}"
            )

            errors.append(
                f"{result['url']}: {error}"
            )

    print(
        f"   ⚠️ Could not download any valid images for: "
        f"{cleaned_query}"
    )

    return None
