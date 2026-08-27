import json
import re
import requests

import ollama
from ddgs import DDGS


MODEL = "qwen3:8b"


# =========================================================
# QWEN JSON HELPERS
# =========================================================

def _extract_json(raw_content: str):
    """
    Extract JSON from common LLM response formats.

    Handles:
    - plain JSON
    - markdown code fences
    - leading/trailing prose
    - <think>...</think> blocks
    """

    if not raw_content:
        raise RuntimeError(
            "Qwen returned an empty response."
        )

    text = raw_content.strip()

    # -----------------------------------------------------
    # REMOVE QWEN THINKING BLOCKS
    # -----------------------------------------------------

    text = re.sub(
        r"<think>.*?</think>",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    ).strip()

    # -----------------------------------------------------
    # REMOVE MARKDOWN CODE FENCES
    # -----------------------------------------------------

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    text = text.strip()

    # -----------------------------------------------------
    # DIRECT JSON PARSE
    # -----------------------------------------------------

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        pass

    # -----------------------------------------------------
    # EXTRACT FIRST JSON ARRAY / OBJECT
    # -----------------------------------------------------

    starts = []

    object_start = text.find("{")
    array_start = text.find("[")

    if object_start >= 0:
        starts.append(
            (object_start, "{", "}")
        )

    if array_start >= 0:
        starts.append(
            (array_start, "[", "]")
        )

    if not starts:
        raise json.JSONDecodeError(
            "No JSON object or array found.",
            text,
            0,
        )

    starts.sort(
        key=lambda item: item[0]
    )

    start, opening, closing = starts[0]

    depth = 0
    in_string = False
    escaped = False

    for index in range(
        start,
        len(text),
    ):

        char = text[index]

        if in_string:

            if escaped:
                escaped = False

            elif char == "\\":
                escaped = True

            elif char == '"':
                in_string = False

            continue

        if char == '"':
            in_string = True
            continue

        if char == opening:
            depth += 1

        elif char == closing:
            depth -= 1

            if depth == 0:

                candidate = text[
                    start:index + 1
                ]

                return json.loads(
                    candidate
                )

    raise json.JSONDecodeError(
        "Could not locate complete JSON.",
        text,
        start,
    )


def ask_qwen_json(
    prompt: str,
    repair_attempts: int = 2,
):
    """
    Ask Qwen for JSON and automatically repair malformed JSON.

    This function is intentionally tolerant of common local
    LLM output issues such as thinking blocks, markdown fences,
    and small amounts of surrounding prose.
    """

    print(
        f"   🤖 Asking {MODEL}..."
    )

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    raw_content = (
        response["message"]["content"]
        .strip()
    )

    print(
        f"   🤖 Qwen response: "
        f"{len(raw_content)} characters"
    )

    # -----------------------------------------------------
    # FIRST ATTEMPT
    # -----------------------------------------------------

    try:
        parsed = _extract_json(
            raw_content
        )

        print(
            "   ✅ Qwen returned valid JSON."
        )

        return parsed

    except (
        json.JSONDecodeError,
        RuntimeError,
    ) as first_error:

        print(
            "   ⚠️ Qwen response was not "
            "immediately parseable."
        )

        print(
            f"   Reason: {first_error}"
        )

    # -----------------------------------------------------
    # REPAIR ATTEMPTS
    # -----------------------------------------------------

    for attempt in range(
        repair_attempts
    ):

        repair_prompt = f"""
You are a JSON repair tool.

The following response was supposed to contain valid JSON:

{raw_content}

Repair the response.

IMPORTANT:

- Return ONLY valid JSON.
- Do not use markdown.
- Do not use code fences.
- Do not include explanations.
- Do not add information.
- Do not remove information.
- Preserve the original structure.
- The final response MUST be parseable by Python json.loads().
"""

        print(
            f"   🔧 Qwen JSON repair "
            f"attempt {attempt + 1}/"
            f"{repair_attempts}"
        )

        repair_response = ollama.chat(
            model=MODEL,
            messages=[
                {
                    "role": "user",
                    "content": repair_prompt,
                }
            ],
        )

        raw_content = (
            repair_response["message"]["content"]
            .strip()
        )

        try:

            parsed = _extract_json(
                raw_content
            )

            print(
                "   ✅ JSON repair succeeded."
            )

            return parsed

        except (
            json.JSONDecodeError,
            RuntimeError,
        ) as repair_error:

            print(
                f"   ⚠️ Repair attempt failed: "
                f"{repair_error}"
            )

    # -----------------------------------------------------
    # FINAL FAILURE
    # -----------------------------------------------------

    preview = raw_content[:2000]

    raise RuntimeError(
        "Qwen returned invalid JSON after "
        f"{repair_attempts} repair attempts.\n\n"
        "Final response preview:\n"
        f"{preview}"
    )


def repair_json(
    raw_content: str,
    expected_structure: str,
):
    """
    Ask the local LLM to repair malformed JSON.

    The model must return JSON only.
    """

    prompt = f"""
You are a JSON repair tool.

The following text was supposed to be valid JSON:

{raw_content}

Repair ONLY the JSON syntax.

Do not change the meaning or content.
Do not add information.
Do not remove information unless required to make
the JSON valid.

The expected structure is:

{expected_structure}

Return ONLY valid JSON.
Do not use markdown.
Do not wrap the JSON in code fences.
Do not include any explanation.
"""

    return ask_qwen_json(
        prompt,
        repair_attempts=2,
    )


# =========================================================
# WEB SEARCH
# =========================================================

def search_web(
    query: str,
    max_results: int = 5,
):
    """
    Search the web using DuckDuckGo.
    """

    results = []

    try:

        with DDGS() as ddgs:

            search_results = ddgs.text(
                query,
                max_results=max_results,
            )

            for result in search_results:

                results.append(
                    {
                        "title": result.get("title"),
                        "url": result.get("href"),
                        "snippet": result.get("body"),
                    }
                )

    except Exception as exc:

        print(
            f" SEARCH FAILED FOR: {query}"
        )

        print(
            f" ERROR: {exc}"
        )

        return []

    return results


# =========================================================
# TOPIC DISCOVERY
# =========================================================

def search_reddit(
    subreddits: list[str],
    limit: int = 10,
    sort: str = "hot",
):
    """
    Fetch trending Reddit posts from multiple subreddits.

    Uses Reddit RSS feeds because the JSON API is blocked.
    """

    import xml.etree.ElementTree as ET

    if not isinstance(
        subreddits,
        list,
    ):
        raise TypeError(
            "subreddits must be a list."
        )

    posts = []
    seen = set()

    namespace = {
        "atom": "http://www.w3.org/2005/Atom"
    }

    print(
        f"🔎 Collecting Reddit trends "
        f"from {len(subreddits)} subreddits..."
    )

    for subreddit in subreddits:

        search_url = (
            f"https://www.reddit.com/r/"
            f"{subreddit}/{sort}.rss"
        )

        try:

            response = requests.get(
                search_url,
                params={
                    "limit": limit,
                },
                headers={
                    "User-Agent": (
                        "ContentEngine/1.0 "
                        "(trend research)"
                    ),
                    "Accept": (
                        "application/rss+xml, "
                        "application/xml"
                    ),
                },
                timeout=10,
            )

            if response.status_code == 429:

                print(
                    f"   ⚠️ r/{subreddit}: "
                    "rate limited — skipping"
                )

                continue

            response.raise_for_status()

            root = ET.fromstring(
                response.text
            )

            entries = root.findall(
                "atom:entry",
                namespace,
            )

            subreddit_count = 0

            for entry in entries[:limit]:

                title = entry.find(
                    "atom:title",
                    namespace,
                )

                link = entry.find(
                    "atom:link",
                    namespace,
                )

                author = entry.find(
                    "atom:author/atom:name",
                    namespace,
                )

                published = entry.find(
                    "atom:published",
                    namespace,
                )

                content = entry.find(
                    "atom:content",
                    namespace,
                )

                title_text = (
                    title.text.strip()
                    if title is not None
                    and title.text
                    else ""
                )

                url = (
                    link.get("href")
                    if link is not None
                    else None
                )

                if not title_text:
                    continue

                identity = (
                    url
                    or title_text.lower()
                )

                if identity in seen:
                    continue

                seen.add(identity)

                posts.append(
                    {
                        "title": title_text,
                        "subreddit": subreddit,
                        "score": None,
                        "comments": None,
                        "url": url,
                        "selftext": (
                            content.text.strip()
                            if content is not None
                            and content.text
                            else ""
                        ),
                        "author": (
                            author.text.strip()
                            if author is not None
                            and author.text
                            else None
                        ),
                        "created_utc": (
                            published.text
                            if published is not None
                            else None
                        ),
                    }
                )

                subreddit_count += 1

            print(
                f"   ✅ r/{subreddit}: "
                f"{subreddit_count} posts"
            )

        except requests.RequestException as exc:

            print(
                f"   ⚠️ r/{subreddit}: "
                f"request failed — "
                f"{type(exc).__name__}: {exc}"
            )

        except ET.ParseError as exc:

            print(
                f"   ⚠️ r/{subreddit}: "
                f"RSS parsing failed — "
                f"{type(exc).__name__}: {exc}"
            )

        except Exception as exc:

            print(
                f"   ⚠️ r/{subreddit}: "
                f"unexpected error — "
                f"{type(exc).__name__}: {exc}"
            )

    print(
        f"🔎 Reddit collection complete: "
        f"{len(posts)} unique posts"
    )

    return posts


def discover_reddit_topics(
    subreddits: list[str],
    limit_per_subreddit: int = 5,
):
    """
    Discover potential content topics from
    trending Reddit discussions.
    """

    posts = search_reddit(
        subreddits,
        limit=limit_per_subreddit,
        sort="hot",
    )

    if not posts:
        return []

    prompt = f"""
You are a content research analyst.

Trending Reddit discussions:

{json.dumps(
    posts,
    indent=2,
    ensure_ascii=False,
)}

Identify the most interesting potential topics
for faceless short-form videos.

Use ONLY information contained in the supplied
Reddit posts.

Return ONLY valid JSON.

Return this structure:

[
    {{
        "topic": "Specific content topic",
        "reason": "Why this Reddit discussion suggests the topic is interesting",
        "source_urls": [
            "Reddit URL"
        ]
    }}
]

Rules:

- Return 5 to 10 topics.
- Each topic must be meaningfully different.
- Prefer highly interesting, unusual, surprising,
  controversial, educational, or curiosity-driven topics.
- Prefer topics that appear likely to attract broad attention.
- Do not invent facts.
- Do not invent Reddit posts or URLs.
- Every source URL must come from the supplied Reddit posts.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    topics = ask_qwen_json(
        prompt
    )

    if isinstance(topics, dict):

        wrapped_topics = topics.get(
            "topics"
        )

        if isinstance(
            wrapped_topics,
            list,
        ):
            topics = wrapped_topics

    if not isinstance(
        topics,
        list,
    ):
        raise RuntimeError(
            "Reddit topic discovery did not "
            "return a JSON array."
        )

    validated_topics = []

    valid_urls = {
        post.get("url")
        for post in posts
        if post.get("url")
    }

    for index, topic in enumerate(
        topics,
        1,
    ):

        if not isinstance(
            topic,
            dict,
        ):
            raise RuntimeError(
                f"Reddit topic {index} "
                "is not a JSON object."
            )

        required_fields = {
            "topic",
            "reason",
            "source_urls",
        }

        missing = (
            required_fields
            - topic.keys()
        )

        if missing:
            raise RuntimeError(
                f"Reddit topic {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
            )

        if not isinstance(
            topic["source_urls"],
            list,
        ):
            raise RuntimeError(
                f"Reddit topic {index} "
                "'source_urls' must be a list."
            )

        for url in topic["source_urls"]:

            if url not in valid_urls:
                raise RuntimeError(
                    f"Reddit topic {index} "
                    f"references an unknown URL: "
                    f"{url}"
                )

        if not topic["topic"].strip():
            raise RuntimeError(
                f"Reddit topic {index} "
                "has an empty topic."
            )

        validated_topics.append(
            topic
        )

    return validated_topics


def discover_best_topic(
    subreddits: list[str],
):
    """
    Discover trending Reddit topics and select
    the strongest candidate for video production.
    """

    topics = discover_reddit_topics(
        subreddits,
        limit_per_subreddit=5,
    )

    if not topics:
        raise RuntimeError(
            "Reddit topic discovery returned no topics."
        )

    prompt = f"""
You are selecting the single best topic for a
faceless short-form video.

Candidate topics:

{json.dumps(
    topics,
    indent=2,
    ensure_ascii=False,
)}

Select the ONE strongest candidate.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "topic": "Selected topic",
    "reason": "Why this is the strongest candidate",
    "source_urls": [
        "Reddit URL"
    ]
}}

Rules:

- The selected topic MUST come from the supplied candidates.
- Do not invent facts.
- Do not invent URLs.
- Every source URL must exist in the supplied candidates.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    selected = ask_qwen_json(
        prompt
    )

    if not isinstance(
        selected,
        dict,
    ):
        raise RuntimeError(
            "Best-topic selection did not return "
            "a JSON object."
        )

    required_fields = {
        "topic",
        "reason",
        "source_urls",
    }

    missing = (
        required_fields
        - selected.keys()
    )

    if missing:
        raise RuntimeError(
            "Best-topic selection is missing fields: "
            + ", ".join(sorted(missing))
        )

    valid_topics = {
        topic["topic"]
        for topic in topics
    }

    if selected["topic"] not in valid_topics:
        raise RuntimeError(
            "Best-topic selection returned "
            "a topic that was not supplied."
        )

    valid_urls = {
        url
        for topic in topics
        for url in topic["source_urls"]
    }

    for url in selected["source_urls"]:

        if url not in valid_urls:
            raise RuntimeError(
                f"Best-topic selection returned "
                f"an unknown URL: {url}"
            )

    return selected


def discover_topics(
    niche: str,
    count: int = 10,
):
    """
    Generate strong short-form video topic opportunities.
    """

    prompt = f"""
You are a content strategist.

Niche:
{niche}

Generate {count} strong short-form video topic opportunities
within this niche.

We want topics that have:
- strong curiosity
- practical value
- potential for viral short-form content
- enough substance to research
- potential for follow-up videos
- potential connection to products, services, tools, or businesses

Return ONLY valid JSON.

Use exactly this structure:

{{
    "topics": [
        {{
            "topic": "Specific video topic",
            "search_query": "Search query that would find useful current information"
        }}
    ]
}}

Requirements:
- Return exactly {count} topics.
- Every topic must be meaningfully different.
- Avoid generic topics.
- Prefer specific, timely, interesting subjects.
- Do not invent statistics or factual claims.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    result = ask_qwen_json(
        prompt
    )

    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "Topic discovery did not return an object."
        )

    topics = result.get(
        "topics"
    )

    if not isinstance(
        topics,
        list,
    ):
        raise RuntimeError(
            "Topic discovery did not return "
            "a topics array."
        )

    if len(topics) != count:
        raise RuntimeError(
            f"Expected {count} topics, "
            f"received {len(topics)}."
        )

    for index, topic in enumerate(
        topics,
        1,
    ):

        if not isinstance(
            topic,
            dict,
        ):
            raise RuntimeError(
                f"Topic {index} is not an object."
            )

        if "topic" not in topic:
            raise RuntimeError(
                f"Topic {index} is missing 'topic'."
            )

        if "search_query" not in topic:
            raise RuntimeError(
                f"Topic {index} is missing "
                "'search_query'."
            )

    return topics


# =========================================================
# RESEARCH ANALYSIS
# =========================================================

def analyze_research(
    query: str,
    results: list,
):
    """
    Analyze supplied search results using Qwen and produce
    evidence-backed claims tied to specific search results.
    """

    prompt = f"""
You are a research assistant.

Research topic:
{query}

Search results:
{json.dumps(results, indent=2)}

Analyze ONLY the supplied search results.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "topic": "{query}",
    "claims": [
        {{
            "claim": "A concise factual claim supported by one supplied search result.",
            "source_index": 0,
            "evidence": "The specific information from the supplied search result that supports the claim."
        }}
    ]
}}

Requirements:

- Every claim MUST be directly supported by one of the supplied search results.
- source_index MUST refer to the zero-based index of the supporting search result.
- Do NOT invent facts, statistics, studies, quotes, names, dates, or locations.
- Do NOT combine information from multiple sources into a single claim.
- If a search result does not provide useful evidence, do not use it.
- Prefer specific, interesting, verifiable claims.
- Evidence should closely reflect what the source actually says.
- Do not infer information that is not explicitly supported.
- Do not invent or modify URLs.
- Return an empty claims array if the supplied results contain insufficient evidence.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    research = ask_qwen_json(
        prompt
    )

    if not isinstance(research, dict):
        raise RuntimeError(
            "Research analyzer did not return "
            "a JSON object."
        )

    # Qwen occasionally omits the redundant topic field.
    # The topic is already known from the function argument.
    if "topic" not in research:
        research["topic"] = query

    if "claims" not in research:
        raise RuntimeError(
            "Research analyzer is missing 'claims'."
        )

    if not isinstance(
        research["claims"],
        list,
    ):
        raise RuntimeError(
            "Research analyzer 'claims' "
            "must be a list."
        )

    validated_claims = []

    for index, claim in enumerate(
        research["claims"],
        1,
    ):

        if not isinstance(
            claim,
            dict,
        ):
            raise RuntimeError(
                f"Research claim {index} "
                "is not an object."
            )

        required_fields = {
            "claim",
            "source_index",
            "evidence",
        }

        missing = (
            required_fields
            - claim.keys()
        )

        if missing:
            raise RuntimeError(
                f"Research claim {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
            )

        source_index = claim[
            "source_index"
        ]

        if not isinstance(
            source_index,
            int,
        ):
            raise RuntimeError(
                f"Research claim {index} "
                "'source_index' must be an integer."
            )

        if not (
            0
            <= source_index
            < len(results)
        ):
            raise RuntimeError(
                f"Research claim {index} "
                f"references invalid source_index "
                f"{source_index}."
            )

        if not claim["claim"].strip():
            raise RuntimeError(
                f"Research claim {index} "
                "has an empty claim."
            )

        if not claim["evidence"].strip():
            raise RuntimeError(
                f"Research claim {index} "
                "has empty evidence."
            )

        validated_claims.append(
            claim
        )

    research["sources"] = [
        {
            "title": result.get("title"),
            "url": result.get("url"),
            "snippet": result.get("snippet"),
        }
        for result in results
    ]

    research["claims"] = validated_claims

    return research


# =========================================================
# TOPIC SCORING
# =========================================================

def score_topic(
    niche: str,
    topic: dict,
    research: dict,
):
    """
    Score one researched topic as a content opportunity.
    """

    prompt = f"""
You are evaluating a short-form content opportunity.

Niche:
{niche}

Candidate topic:
{topic["topic"]}

Search query:
{topic["search_query"]}

Research:
{json.dumps(research, indent=2)}

Score this topic as a potential content opportunity.

Use a 1-10 score for each:

- content_potential
- novelty
- monetization_potential
- follow_up_potential
- research_quality

Then calculate an overall_score from 1-10.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "topic": "{topic["topic"]}",
    "search_query": "{topic["search_query"]}",
    "content_potential": 1,
    "novelty": 1,
    "monetization_potential": 1,
    "follow_up_potential": 1,
    "research_quality": 1,
    "overall_score": 1,
    "reason": "Brief explanation of why this is or is not a strong opportunity."
}}

Requirements:
- Scores must be integers from 1 to 10.
- Base research_quality only on the supplied research.
- Do not invent statistics.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include anything before or after the JSON.
"""

    score = ask_qwen_json(
        prompt
    )

    if not isinstance(
        score,
        dict,
    ):
        raise RuntimeError(
            "Topic scoring did not return a JSON object."
        )

    required_fields = {
        "topic",
        "search_query",
        "content_potential",
        "novelty",
        "monetization_potential",
        "follow_up_potential",
        "research_quality",
        "overall_score",
        "reason",
    }

    missing = (
        required_fields
        - score.keys()
    )

    if missing:
        raise RuntimeError(
            "Topic scoring is missing fields: "
            + ", ".join(sorted(missing))
        )

    return score


# =========================================================
# CONTENT GENERATION
# =========================================================

def generate_content(
    query: str,
    research: dict,
    count: int = 5,
):
    """
    Generate distinct faceless short-form video
    content packages using only evidence-backed research.
    """

    if count == 1:

        angle_instruction = """
Create ONE strong short-form video.

Choose the single strongest angle for this topic.
Prioritize curiosity, surprise, and clear explanation.
"""

    else:

        angle_instruction = f"""
Create {count} DISTINCT faceless short-form video content packages.

Each package must approach the topic from a meaningfully different
angle. Do NOT simply rewrite the same script.

Use these angles where appropriate:

1. SURPRISING / ATTENTION-GRABBING
2. EXPLAINER
3. PRACTICAL
4. RISK / CONTROVERSY
5. FUTURE / PREDICTION
"""

    prompt = f"""
You are a short-form content strategist.

Topic:
{query}

Evidence-backed research:
{json.dumps(research, indent=2, ensure_ascii=False)}

{angle_instruction}

IMPORTANT FACTUAL ACCURACY RULES:

- You may ONLY make factual claims contained in the supplied
  research "claims" array.
- Do NOT introduce outside facts.
- Do NOT invent statistics.
- Do NOT invent names, dates, locations, studies, companies,
  discoveries, quotes, or numbers.
- Do NOT infer facts that are not explicitly supported.
- If the research does not support a detail, leave that detail out.
- Do NOT fabricate citations or URLs.
- Treat the supplied research as the complete factual boundary
  for the narration.

Return ONLY a JSON array.

The response MUST contain exactly {count} object(s).

Even when count is 1, you MUST return a JSON array
containing one object.

Each object MUST use exactly these fields:

{{
    "angle": "The strategic angle used for this video.",
    "hook": "A compelling opening sentence.",
    "narration": "The complete spoken narration for a 30-60 second video.",
    "title": "A short attention-grabbing title.",
    "description": "A short description suitable for social media.",
    "cta": "A natural call to action."
}}

Requirements:

- Every factual statement in narration must be supported by
  the supplied research.
- "hook" must be supported by the research if it contains
  a factual claim.
- "narration" contains ONLY words that should actually be spoken.
- Do NOT include labels such as HOOK, TITLE, DESCRIPTION, CTA,
  or ANGLE inside narration.
- Narration should contain approximately 80-140 words.
- Do not use markdown.
- Do not use code fences.
- Do not include anything before or after the JSON array.
"""

    print(
        "\n   🧠 Generating content with "
        f"{MODEL}..."
    )

    try:
        content = ask_qwen_json(
            prompt
        )

    except Exception as exc:

        print(
            "\n   ❌ CONTENT GENERATION ERROR"
        )

        print(
            f"   {type(exc).__name__}: {exc}"
        )

        raise

    if isinstance(
        content,
        dict,
    ):

        # Gracefully handle the common
        # {"content": [...]} response.

        for key in (
            "content",
            "contents",
            "packages",
            "videos",
        ):

            wrapped = content.get(
                key
            )

            if isinstance(
                wrapped,
                list,
            ):

                content = wrapped
                break

    if not isinstance(
        content,
        list,
    ):
        raise RuntimeError(
            "Content generation did not return "
            "a JSON array."
        )

    if len(content) != count:
        raise RuntimeError(
            f"Expected {count} content packages, "
            f"received {len(content)}."
        )

    required_fields = {
        "angle",
        "hook",
        "narration",
        "title",
        "description",
        "cta",
    }

    for index, package in enumerate(
        content,
        1,
    ):

        if not isinstance(
            package,
            dict,
        ):
            raise RuntimeError(
                f"Content package {index} "
                "is not a JSON object."
            )

        missing = (
            required_fields
            - package.keys()
        )

        if missing:
            raise RuntimeError(
                f"Content package {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
            )

        for field in required_fields:

            value = package.get(
                field
            )

            if not isinstance(
                value,
                str,
            ):
                raise RuntimeError(
                    f"Content package {index} "
                    f"field '{field}' must be a string."
                )

            if not value.strip():
                raise RuntimeError(
                    f"Content package {index} "
                    f"field '{field}' is empty."
                )

    print(
        f"   ✅ Generated {len(content)} "
        "content package(s)."
    )

    return content


# =========================================================
# VISUAL PLAN
# =========================================================

def generate_visual_plan(
    topic: str,
    narration: str,
):
    """
    Generate a visual scene plan for a video narration.
    """

    prompt = f"""
You are a visual director for a faceless short-form video.

Topic:
{topic}

Narration:
{narration}

Break the narration into 3-6 visual scenes.

Return ONLY valid JSON.

Use exactly this structure:

{{
    "scenes": [
        {{
            "visual": "What should be shown visually.",
            "search": "Simple search keywords for finding a suitable image.",
            "duration": 5
        }}
    ]
}}

Requirements:

- Create 3-6 scenes.
- Scenes should follow the progression of the narration.
- "visual" describes what the viewer should see.
- "search" contains simple practical image-search keywords.
- "duration" is an approximate number of seconds.
- Keep visuals easy to source automatically.
- Do not include scene numbers.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include any text before or after the JSON.
"""

    visual_plan = ask_qwen_json(
        prompt
    )

    if not isinstance(
        visual_plan,
        dict,
    ):
        raise RuntimeError(
            "Visual plan must be a JSON object."
        )

    if "scenes" not in visual_plan:
        raise RuntimeError(
            "Visual plan is missing 'scenes'."
        )

    if not isinstance(
        visual_plan["scenes"],
        list,
    ):
        raise RuntimeError(
            "Visual plan 'scenes' must be a list."
        )

    if not 3 <= len(
        visual_plan["scenes"]
    ) <= 6:
        raise RuntimeError(
            "Visual plan must contain between "
            "3 and 6 scenes."
        )

    for index, scene in enumerate(
        visual_plan["scenes"],
        1,
    ):

        if not isinstance(
            scene,
            dict,
        ):
            raise RuntimeError(
                f"Visual scene {index} "
                "is not a JSON object."
            )

        required_fields = {
            "visual",
            "search",
            "duration",
        }

        missing = (
            required_fields
            - scene.keys()
        )

        if missing:
            raise RuntimeError(
                f"Visual scene {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
            )

        if not isinstance(
            scene["duration"],
            (int, float),
        ):
            raise RuntimeError(
                f"Visual scene {index} "
                "'duration' must be numeric."
            )

        if scene["duration"] <= 0:
            raise RuntimeError(
                f"Visual scene {index} "
                "'duration' must be greater than zero."
            )

    return visual_plan