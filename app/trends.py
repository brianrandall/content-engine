from dataclasses import dataclass, field
from datetime import datetime, timezone
import requests
import json

from app.research import ask_qwen_json


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

    def to_dict(self):
        return {
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "published_at": self.published_at,
            "engagement": self.engagement,
            "metadata": self.metadata,
        }

def reddit_posts_to_trends(
    posts: list[dict],
):
    """
    Convert Reddit research results into normalized
    TrendItem objects.
    """

    trends = []

    for post in posts:

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

import requests


HN_TOP_STORIES = (
    "https://hacker-news.firebaseio.com/"
    "v0/topstories.json"
)

HN_ITEM = (
    "https://hacker-news.firebaseio.com/"
    "v0/item/{item_id}.json"
)


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

def collect_trends(
    reddit_subreddits: list[str] | None = None,
    reddit_limit: int = 5,
    hackernews_limit: int = 20,
):
    """
    Collect trends from all currently supported sources.
    """

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

    return trends

def rank_trending_topics(
    trends: list[TrendItem],
    count: int = 10,
):
    """
    Use Qwen to identify and rank the strongest
    short-form video topics from collected trends.
    """

    if not trends:
        return []

    trend_data = [
        trend.to_dict()
        for trend in trends
    ]

    prompt = f"""
You are a short-form content research analyst.

Below is a collection of current internet trends.

Trend data:
{json.dumps(
    trend_data,
    indent=2,
    ensure_ascii=False,
)}

Identify the strongest potential topics for
faceless short-form videos.

Return ONLY valid JSON.

Return exactly this structure:

[
    {{
        "topic": "Specific video topic",
        "reason": "Why this topic has strong content potential",
        "sources": [
            {{
                "source": "reddit or hackernews",
                "title": "Original trend title",
                "url": "Original URL"
            }}
        ]
    }}
]

Rules:

- Return up to {count} topics.
- Prefer topics with strong curiosity.
- Prefer surprising, unusual, counterintuitive,
  controversial, or highly interesting subjects.
- Prefer topics that can be explained clearly
  in 30-90 seconds.
- Every topic MUST be supported by supplied trend data.
- Do NOT invent facts.
- Do NOT invent URLs.
- Do NOT invent sources.
- Do NOT combine unrelated trends.
- A topic may use multiple sources only when
  those sources clearly concern the same subject.
- Preserve source titles and URLs exactly.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    topics = ask_qwen_json(prompt)

    if not isinstance(topics, list):
        raise RuntimeError(
            "Trend topic ranking did not return "
            "a JSON array."
        )

    valid_sources = {
        (
            trend.source,
            trend.title,
            trend.url,
        )
        for trend in trends
    }

    validated_topics = []

    for index, topic in enumerate(
        topics,
        1,
    ):

        if not isinstance(topic, dict):
            raise RuntimeError(
                f"Trending topic {index} "
                "is not a JSON object."
            )

        required_fields = {
            "topic",
            "reason",
            "sources",
        }

        missing = (
            required_fields
            - topic.keys()
        )

        if missing:
            raise RuntimeError(
                f"Trending topic {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
            )

        if not isinstance(
            topic["sources"],
            list,
        ):
            raise RuntimeError(
                f"Trending topic {index} "
                "'sources' must be a list."
            )

        for source in topic["sources"]:

            if not isinstance(
                source,
                dict,
            ):
                raise RuntimeError(
                    f"Trending topic {index} "
                    "contains an invalid source."
                )

            required_source_fields = {
                "source",
                "title",
                "url",
            }

            missing_source_fields = (
                required_source_fields
                - source.keys()
            )

            if missing_source_fields:
                raise RuntimeError(
                    f"Trending topic {index} "
                    "source is missing fields: "
                    + ", ".join(
                        sorted(
                            missing_source_fields
                        )
                    )
                )

            source_key = (
                source["source"],
                source["title"],
                source["url"],
            )

            if source_key not in valid_sources:
                raise RuntimeError(
                    f"Trending topic {index} "
                    "references an unknown source."
                )

        if not topic["topic"].strip():
            raise RuntimeError(
                f"Trending topic {index} "
                "has an empty topic."
            )

        if not topic["reason"].strip():
            raise RuntimeError(
                f"Trending topic {index} "
                "has an empty reason."
            )

        validated_topics.append(topic)

    return validated_topics