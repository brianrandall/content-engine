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
    source_url: str | None = None,
    title: str | None = None,
):
    output_path = ASSETS_DIR / filename

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

    # Make sure we actually received something.
    if not response.content:
        raise requests.RequestException(
            "Downloaded image was empty."
        )

    output_path.write_bytes(response.content)

    metadata_path = output_path.with_suffix(".json")

    metadata = {
        "filename": filename,
        "image_url": url,
        "source_url": source_url,
        "title": title,
    }

    metadata_path.write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    return output_path


def get_image(query: str, filename: str):
    """
    Find and download the first usable image.

    Search failures and individual download failures do not
    crash the pipeline.
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
            return download_image(
                result["url"],
                filename,
                source_url=result.get("source"),
                title=result.get("title"),
            )

        except requests.RequestException as error:

            print(
                f"   ⚠️ Image {index} failed: {error}"
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
        f"   ⚠️ Could not download any images for: "
        f"{cleaned_query}"
    )

    return None