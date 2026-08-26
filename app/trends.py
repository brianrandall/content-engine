from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json

import requests

from app.research import ask_qwen_json


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

    if not trends:
        return []

    from app.topic_history import (
        filter_covered_trends,
        load_topic_history,
        recent_topics,
    )

    history = load_topic_history()
    trends = filter_covered_trends(
        trends,
        history,
    )

    if not trends:
        return []

    covered_topics = recent_topics(
        history,
    )

    trend_data = [
        {
            "source_index": index,
            "title": trend.title,
            "url": trend.url,
            "source": trend.source,
        }
        for index, trend in enumerate(trends)
    ]

    prompt = f"""
You are the senior editorial strategist for a large
faceless short-form video network.

Your job is NOT to summarize trends.

Your job is to find STORIES inside the supplied trend data
that could become compelling 30-90 second videos.

Think like an editor deciding:

"Would I actually make a video about this?"

Trend data:

{json.dumps(
    trend_data,
    indent=2,
    ensure_ascii=False,
)}

Recently covered topics. Do not select these stories again:

{json.dumps(
    covered_topics,
    indent=2,
    ensure_ascii=False,
)}

---

WHAT MAKES A GOOD VIDEO TOPIC?

A strong topic should contain at least one of these:

- something surprising
- something people are suddenly talking about
- something strange or bizarre
- something that challenges what people assume
- something with a clear conflict or tension
- something with an interesting "why?"
- something with a strong human story
- something that reveals something people didn't know
- something that makes people ask "wait, what?"
- something with obvious visual storytelling potential
- something consequential that ordinary people would care about

The topic should make someone want to CLICK before they
even know the full story.

---

BAD TOPICS:

Do NOT return topics that are merely:

- product launches
- software releases
- developer tools
- GitHub projects
- technical announcements
- minor updates
- generic political news
- generic economic news
- generic technology news
- niche community discussions
- academic papers with no compelling story
- lists of tools
- "X is trending"
- "People are discussing X"
- descriptions of websites
- descriptions of Reddit posts
- obvious summaries of the supplied headlines

A topic being technically interesting does NOT make it
a good short-form video.

For example:

BAD:
"Language server for code editing"

GOOD:
Only if the supplied data contains an actual surprising
story involving the technology.

BAD:
"Self-hosted ticketing system"

GOOD:
Only if there is a genuinely interesting story surrounding
why people are suddenly building their own ticketing systems.

---

TURN TRENDS INTO VIDEO PREMISES

Do not simply copy the title.

Instead, ask:

"What is the actual story here?"

"What would make a normal person care?"

"What is the most interesting question hidden inside
this trend?"

"What would make someone stop scrolling?"

For example:

Trend:
"Study finds X behaves differently than expected"

Potential video topic:
"Scientists expected X to behave one way. It didn't."

Trend:
"Unexpected discovery in Antarctica"

Potential video topic:
"Something was found beneath Antarctica that scientists
weren't expecting."

These are examples of STRUCTURE only.

Do not invent facts from them.

---

EVIDENCE BOUNDARY

Every topic MUST be supported by the supplied trend data.

You may reinterpret the editorial angle.

You may NOT invent:

- facts
- people
- events
- statistics
- dates
- locations
- companies
- scientific findings
- explanations
- consequences
- quotes

If the supplied data does not support an interesting story,
discard it.

Do NOT manufacture a story just because we need {count}
results.

---

DIVERSITY

The final topics must represent genuinely different stories.

Do NOT select:

- multiple topics about the same event
- multiple topics about the same company
- multiple topics about the same person
- multiple angles on one story
- multiple versions of the same technology story

If five trend items are really one story, treat them as ONE
opportunity.

Prefer eight different stories over eight variations
of the same story.

---

EDITORIAL TEST

Before selecting a topic, mentally complete:

"People should watch this because..."

If the answer is basically:

"because this is an interesting software project"

discard it.

If the answer is:

"because this is something unexpected that people will
want explained"

keep it.

---

RANKING

Rank opportunities using these priorities:

1. Stop-scroll curiosity
2. Surprise / unusualness
3. Broad audience appeal
4. Storytelling potential
5. Visual potential
6. Emotional or human interest
7. Timeliness
8. Ability to explain the story clearly in 30-90 seconds

Do NOT prioritize technical sophistication.

Do NOT prioritize how impressive the source is.

Prioritize whether the STORY is interesting.

Prefer timely real-world headline events over generic facts,
evergreen trivia, or abstract discussions.

---

CATEGORY

Assign one broad category:

- science
- technology
- business
- entertainment
- culture
- politics
- world
- history
- internet
- human-interest
- other

---

OUTPUT

Return ONLY valid JSON.

Return a JSON array containing UP TO {count} topics.

Do NOT pad the list.

If only 4 genuinely strong video opportunities exist,
return 4.

Each object MUST contain exactly:

{{
    "topic": "The actual video-worthy story/topic",
    "reason": "Why this story is worth making a short-form video about",
    "category": "Broad category",
    "source_indices": [
        0
    ]
}}

Rules:

- topic must describe a compelling story or premise.
- topic must NOT simply copy the source title.
- reason must explain the editorial opportunity.
- category must be one of the categories above.
- Every source_index MUST be an integer referring to the
    zero-based index of the supplied trends list.
- Do not invent source_indices; use only indices that exist
    in the supplied trends list.
- Use multiple source_indices only when they clearly describe
  the same underlying story.
- Prefer one source_index when sufficient.
- Do not invent information.
- Do not invent source_indices.
- Do not invent stories.
- Do not use markdown.
- Do not use code fences.
- Do not include commentary.
- Do not include anything before or after the JSON.

Order the topics from strongest opportunity to weakest.
"""

    topics = ask_qwen_json(prompt)

    if not isinstance(topics, list):
        raise RuntimeError(
            "Trend topic ranking did not return "
            "a JSON array."
        )

    validated_topics = []

    for index, topic in enumerate(topics, 1):

        if not isinstance(topic, dict):
            raise RuntimeError(
                f"Trending topic {index} "
                "is not a JSON object."
            )

        required_fields = {
            "topic",
            "reason",
            "category",
            "source_indices",
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

        if not isinstance(topic["topic"], str):
            raise RuntimeError(
                f"Trending topic {index} "
                "'topic' must be a string."
            )

        if not topic["topic"].strip():
            raise RuntimeError(
                f"Trending topic {index} "
                "has an empty topic."
            )

        if not isinstance(topic["reason"], str):
            raise RuntimeError(
                f"Trending topic {index} "
                "'reason' must be a string."
            )

        if not topic["reason"].strip():
            raise RuntimeError(
                f"Trending topic {index} "
                "has an empty reason."
            )

        if not isinstance(topic["category"], str):
            raise RuntimeError(
                f"Trending topic {index} "
                "'category' must be a string."
            )

        if not topic["category"].strip():
            raise RuntimeError(
                f"Trending topic {index} "
                "has an empty category."
            )

        if not isinstance(topic["source_indices"], list):
            print(
                f"   ⚠️ Trending topic {index} "
                "has invalid source_indices: "
                "expected a list"
            )
            continue

        if not topic["source_indices"]:
            print(
                f"   ⚠️ Trending topic {index} "
                "has no source_indices."
            )
            continue

        resolved_sources = []
        valid_topic = True

        for source_index in topic["source_indices"]:

            if (
                not isinstance(source_index, int)
                or isinstance(source_index, bool)
                or not 0 <= source_index < len(trends)
            ):
                print(
                    f"   ⚠️ Trending topic {index} "
                    f"references invalid source_index: "
                    f"{source_index}"
                )

                valid_topic = False
                break

            resolved_sources.append(
                trends[source_index]
            )

        if not valid_topic:
            continue

        validated_topics.append(
            {
                "topic": topic["topic"].strip(),
                "reason": topic["reason"].strip(),
                "category": topic["category"].strip(),
                "source_indices": topic["source_indices"],
                "sources": resolved_sources,
            }
        )

    return validated_topics