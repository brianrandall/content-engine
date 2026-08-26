from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib

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

        trends.extend(
            fetch_google_news_trends(
                limit=30
            )
        )

    except Exception as exc:

        print(
            "Google News collection failed: "
            f"{type(exc).__name__}: {exc}"
        )

    return trends


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