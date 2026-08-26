from datetime import datetime, timezone
import email.utils
import xml.etree.ElementTree as ET

import requests

from app.trends import TrendItem


GOOGLE_NEWS_RSS_URL = (
    "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
)


def fetch_google_news_trends(
    limit: int = 30,
):
    """Fetch current top stories from Google News RSS."""

    response = requests.get(
        GOOGLE_NEWS_RSS_URL,
        headers={"User-Agent": "content-engine/1.0"},
        timeout=20,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    trends = []

    for item in root.findall("./channel/item")[:limit]:
        title = item.findtext("title")
        url = item.findtext("link")

        if not title or not url:
            continue

        published_at = None
        published_text = item.findtext("pubDate")

        if published_text:
            try:
                published_at = datetime.fromtimestamp(
                    email.utils.parsedate_to_datetime(
                        published_text
                    ).timestamp(),
                    tz=timezone.utc,
                ).isoformat()
            except (TypeError, ValueError, OverflowError):
                pass

        source_element = item.find("source")
        source_name = (
            source_element.text
            if source_element is not None
            else "Google News"
        )

        trends.append(
            TrendItem(
                source="google_news",
                title=title,
                url=url,
                content="",
                published_at=published_at,
                metadata={
                    "publisher": source_name,
                },
            )
        )

    return trends
