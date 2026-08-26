from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import re
import xml.etree.ElementTree as ET

import requests


# =========================================================
# CONFIG
# =========================================================

DEFAULT_REDDIT_SUBREDDITS = [
    "news",
    "worldnews",
    "technology",
    "science",
    "business",
    "entertainment",
    "movies",
    "popculture",
    "interestingasfuck",
    "todayilearned",
]

HN_TOP_STORIES = (
    "https://hacker-news.firebaseio.com/"
    "v0/topstories.json"
)

HN_ITEM = (
    "https://hacker-news.firebaseio.com/"
    "v0/item/{item_id}.json"
)

GOOGLE_NEWS_SEARCH_URL = (
    "https://news.google.com/rss/search"
)

GOOGLE_NEWS_QUERIES = (
    ("entertainment", "celebrity OR actor OR musician OR star when:1d"),
    ("weird", "weird OR bizarre OR unusual OR viral when:1d"),
    ("technology", "technology OR AI OR artificial intelligence when:1d"),
    ("science", "science discovery OR space discovery when:1d"),
    ("business", "business OR economy OR money OR markets when:1d"),
    ("politics", "politics election government when:1d"),
    ("world", "world news conflict crisis when:1d"),
    ("internet", "internet OR social media platform when:1d"),
    ("human-interest", "human interest OR rescue OR community when:1d"),
    ("sports", "sports championship controversy upset scandal when:1d"),
)

LOW_VALUE_HEADLINE_PATTERNS = (
    r"\brankings?\b",
    r"\bodds\b",
    r"\bpicks\b",
    r"\bpredictions?\b",
    r"\bpreview\b",
    r"\bschedule\b",
    r"\bpower rankings?\b",
    r"\btop\s+100\b",
    r"\bwatch\b",
    r"\banalysis\b",
    r"\brumou?rs?\b",
    r"\bbetting\b",
    r"\bfantasy\b",
    r"\bprojections?\b",
)


# =========================================================
# TREND MODEL
# =========================================================

@dataclass
class TrendItem:
    """
    Normalized representation of something interesting
    discovered from an external source.
    """

    source: str
    title: str
    url: str | None = None
    content: str = ""
    published_at: str | None = None

    engagement: dict = field(
        default_factory=dict
    )

    metadata: dict = field(
        default_factory=dict
    )

    source_id: str = ""

    def __post_init__(self):
        if not self.source_id:
            identity = (
                f"{self.source}|"
                f"{self.title}|"
                f"{self.url or ''}"
            )

            self.source_id = hashlib.sha1(
                identity.encode("utf-8")
            ).hexdigest()[:12]

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "published_at": self.published_at,
            "engagement": self.engagement,
            "metadata": self.metadata,
        }


# =========================================================
# REDDIT
# =========================================================

def reddit_posts_to_trends(
    posts: list[dict],
):
    """
    Convert Reddit research results into normalized
    TrendItem objects.
    """

    trends = []

    for post in posts:

        source_id = post.get("id")

        trends.append(
            TrendItem(
                source="reddit",
                title=post.get(
                    "title",
                    "",
                ),
                url=post.get(
                    "url"
                ),
                content=post.get(
                    "selftext",
                    "",
                ),
                published_at=post.get(
                    "created_utc"
                ),
                source_id=f"reddit:{source_id}" if source_id else None,
                engagement={
                    "score": post.get(
                        "score"
                    ),
                    "comments": post.get(
                        "comments"
                    ),
                },
                metadata={
                    "subreddit": post.get(
                        "subreddit"
                    ),
                    "author": post.get(
                        "author"
                    ),
                },
            )
        )

    return trends


# =========================================================
# HACKER NEWS
# =========================================================

def fetch_hackernews_trends(
    limit: int = 20,
):
    """
    Fetch top Hacker News stories and normalize them.
    """

    response = requests.get(
        HN_TOP_STORIES,
        timeout=20,
    )

    response.raise_for_status()

    story_ids = response.json()

    trends = []

    for story_id in story_ids[:limit]:

        item_response = requests.get(
            HN_ITEM.format(
                item_id=story_id
            ),
            timeout=20,
        )

        if not item_response.ok:
            continue

        item = item_response.json()

        if not item:
            continue

        if item.get("type") != "story":
            continue

        title = item.get(
            "title"
        )

        if not title:
            continue

        url = item.get(
            "url"
        )

        if not url:
            url = (
                "https://news.ycombinator.com/item?id="
                f"{story_id}"
            )

        published_at = None

        if item.get("time"):
            published_at = datetime.fromtimestamp(
                item["time"],
                tz=timezone.utc,
            ).isoformat()

        trends.append(
            TrendItem(
                source="hackernews",
                title=title,
                url=url,
                content="",
                published_at=published_at,
                source_id=f"hackernews:{story_id}",
                engagement={
                    "score": item.get(
                        "score"
                    ),
                    "comments": item.get(
                        "descendants"
                    ),
                },
                metadata={
                    "author": item.get(
                        "by"
                    ),
                    "hn_id": story_id,
                },
            )
        )

    return trends


def _headline_key(title: str):
    return " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            title.casefold(),
        ).split()
    )


def is_low_value_headline(title: str):
    return any(
        re.search(pattern, title, re.IGNORECASE)
        for pattern in LOW_VALUE_HEADLINE_PATTERNS
    )


def fetch_google_news_query(
    query: str,
    category: str,
    limit: int = 8,
):
    params = {
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }
    response = requests.get(
        GOOGLE_NEWS_SEARCH_URL,
        params=params,
        headers={"User-Agent": "content-engine/1.0"},
        timeout=20,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    trends = []

    for item in root.findall("./channel/item")[:limit]:
        title = item.findtext("title")
        url = item.findtext("link")

        if not title or not url or is_low_value_headline(title):
            continue

        published_at = item.findtext("pubDate")
        source_element = item.find("source")
        publisher = (
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
                    "publisher": publisher,
                    "query": query,
                    "category": category,
                },
            )
        )

    return trends


def _dedupe_trends(trends):
    unique_trends = []
    seen_urls = set()
    seen_headlines = set()

    for trend in trends:
        headline_key = _headline_key(trend.title)

        if trend.url and trend.url in seen_urls:
            continue

        if headline_key in seen_headlines:
            continue

        if any(
            SequenceMatcher(
                None,
                headline_key,
                _headline_key(existing.title),
            ).ratio() >= 0.9
            for existing in unique_trends
        ):
            continue

        unique_trends.append(trend)
        seen_headlines.add(headline_key)
        if trend.url:
            seen_urls.add(trend.url)

    return unique_trends


def _print_collection_summary(trends):
    source_counts = {}
    category_counts = {}

    for trend in trends:
        source_counts[trend.source] = (
            source_counts.get(trend.source, 0) + 1
        )
        category = trend.metadata.get(
            "category",
            "uncategorized",
        )
        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

    print(
        "Trend collection summary: "
        f"{len(trends)} unique candidates"
    )
    print(
        "  Sources: "
        + ", ".join(
            f"{source}={count}"
            for source, count in sorted(source_counts.items())
        )
    )
    print(
        "  Categories: "
        + ", ".join(
            f"{category}={count}"
            for category, count in sorted(category_counts.items())
        )
    )


# =========================================================
# COLLECT
# =========================================================

def collect_trends(
    reddit_subreddits: list[str] | None = None,
    reddit_limit: int = 5,
    hackernews_limit: int = 20,
):
    """
    Collect trends from all currently supported sources.
    """

    if reddit_subreddits is None:
        reddit_subreddits = DEFAULT_REDDIT_SUBREDDITS

    trends = []

    # -----------------------------------------------------
    # REDDIT
    # -----------------------------------------------------

    if reddit_subreddits:

        from app.research import search_reddit

        try:

            reddit_posts = search_reddit(
                reddit_subreddits,
                limit=reddit_limit,
                sort="hot",
            )

            trends.extend(
                reddit_posts_to_trends(
                    reddit_posts
                )
            )

        except Exception as exc:

            print(
                "Reddit trend collection failed: "
                f"{type(exc).__name__}: {exc}"
            )

    # -----------------------------------------------------
    # HACKER NEWS
    # -----------------------------------------------------

    try:

        trends.extend(
            fetch_hackernews_trends(
                limit=hackernews_limit
            )
        )

    except Exception as exc:

        print(
            "Hacker News trend collection failed: "
            f"{type(exc).__name__}: {exc}"
        )

    # -----------------------------------------------------
    # GOOGLE NEWS
    # -----------------------------------------------------

    try:

        from app.news import fetch_google_news_trends

        for category, query in GOOGLE_NEWS_QUERIES:
            try:
                trends.extend(
                    fetch_google_news_query(
                        query,
                        category,
                    )
                )
            except Exception as exc:
                print(
                    "Google News query failed "
                    f"({category}): "
                    f"{type(exc).__name__}: {exc}"
                )

        # Retain the existing front-page source as a fallback/enrichment
        # source while applying the same filtering and deduplication.
        trends.extend(
            fetch_google_news_trends(
                limit=20
            )
        )

    except Exception as exc:

        print(
            "Google News collection failed: "
            f"{type(exc).__name__}: {exc}"
        )

    filtered_trends = [
        trend
        for trend in trends
        if not is_low_value_headline(trend.title)
    ]
    unique_trends = _dedupe_trends(
        filtered_trends
    )
    _print_collection_summary(
        unique_trends
    )

    return unique_trends


# =========================================================
# RANK
# =========================================================

def rank_trending_topics(
    trends: list[TrendItem],
    count: int = 8,
):
    """
    Use Qwen to identify the strongest short-form video
    opportunities from collected trend data.

    The goal is to generate actual video-worthy story
    concepts rather than simply returning trend titles.
    """

    from app.editorial import evaluate_and_select

    if not trends:
        rank_trending_topics.last_diagnostics = {
            "raw_trend_count": 0,
            "normalized_candidate_count": 0,
            "evaluated_candidate_count": 0,
            "category_distribution": {},
            "evaluations": [],
        }
        return []

    from app.topic_history import (
        filter_covered_trends,
        load_topic_history,
    )

    history = load_topic_history()
    filtered_trends = filter_covered_trends(
        trends,
        history,
    )
    topics, diagnostics = evaluate_and_select(
        filtered_trends,
        count,
    )
    diagnostics["raw_trend_count"] = len(trends)
    diagnostics["covered_trend_count"] = (
        len(trends) - len(filtered_trends)
    )
    rank_trending_topics.last_diagnostics = diagnostics
    return topics