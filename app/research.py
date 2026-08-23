import json

import ollama
from ddgs import DDGS


MODEL = "qwen3:8b"


# =========================================================
# QWEN JSON HELPERS
# =========================================================

def ask_qwen_json(
    prompt: str,
    repair_attempts: int = 2,
):
    """
    Ask Qwen for JSON and automatically repair malformed JSON.
    """

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    raw_content = response["message"]["content"].strip()

    for attempt in range(repair_attempts + 1):

        try:
            return json.loads(raw_content)

        except json.JSONDecodeError:

            if attempt >= repair_attempts:
                raise RuntimeError(
                    "Qwen returned invalid JSON "
                    "after repair attempts."
                )

            repair_prompt = f"""
The following response was supposed to be valid JSON,
but it contains a JSON formatting error.

Repair the JSON.

IMPORTANT:
- Preserve the original information.
- Do not add new information.
- Do not remove valid information.
- Return ONLY valid JSON.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include any explanation.

Malformed JSON:

{raw_content}
"""

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

            print(
                f"   🔧 Qwen JSON repair "
                f"attempt {attempt + 1}"
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
Do not remove information unless required to make the JSON valid.

The expected structure is:

{expected_structure}

Return ONLY valid JSON.
Do not use markdown.
Do not wrap the JSON in code fences.
Do not include any explanation.
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    repaired = (
        response["message"]["content"]
        .strip()
    )

    try:
        return json.loads(repaired)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "JSON repair failed.\n"
            f"Repaired output:\n{repaired}"
        ) from exc


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

    if not isinstance(result, dict):
        raise RuntimeError(
            "Topic discovery did not return an object."
        )

    topics = result.get("topics")

    if not isinstance(topics, list):
        raise RuntimeError(
            "Topic discovery did not return a topics array."
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

        if not isinstance(topic, dict):
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
    Analyze supplied search results using Qwen.
    """

    prompt = f"""
You are a research assistant.

Research topic:
{query}

Search results:
{json.dumps(results, indent=2)}

Analyze the research and return ONLY valid JSON.

Use exactly this structure:

{{
    "topic": "{query}",
    "key_facts": [
        "Important factual finding supported by the sources."
    ],
    "statistics": [
        "Important statistic supported by the sources."
    ],
    "interesting_findings": [
        "Interesting or useful finding supported by the sources."
    ],
    "content_angles": [
        "Potential angle for a short-form video."
    ],
    "surprising_findings": [
        "Unexpected or counterintuitive finding supported by the sources."
    ],
    "sources": [
        {{
            "title": "Source title",
            "url": "Source URL"
        }}
    ]
}}

Requirements:

- Only include information supported by the supplied search results.
- Do not invent facts, statistics, companies, studies, or quotes.
- If a category has no useful information, return an empty array.
- Keep findings concise.
- Prioritize facts that could become compelling short-form content.
- Preserve source URLs so individual claims can be traced back later.
- Do not use markdown.
- Do not wrap the JSON in code fences.
- Do not include any text before or after the JSON.
"""

    research = ask_qwen_json(
        prompt
    )

    if not isinstance(research, dict):
        raise RuntimeError(
            "Research analyzer did not return a JSON object."
        )

    required_fields = {
        "topic",
        "key_facts",
        "statistics",
        "interesting_findings",
        "content_angles",
        "surprising_findings",
        "sources",
    }

    missing = required_fields - research.keys()

    if missing:
        raise RuntimeError(
            "Research analyzer is missing fields: "
            + ", ".join(sorted(missing))
        )

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

    if not isinstance(score, dict):
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

    missing = required_fields - score.keys()

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
    Generate multiple distinct faceless short-form video
    content packages from supplied research.
    """

    prompt = f"""
You are a short-form content strategist.

Topic:
{query}

Research:
{json.dumps(research, indent=2)}

Create {count} DISTINCT faceless short-form video content packages
based ONLY on the supplied research.

Each package must approach the topic from a meaningfully different
angle. Do NOT simply rewrite the same script.

Use these angles:

1. SURPRISING / ATTENTION-GRABBING
2. EXPLAINER
3. PRACTICAL
4. RISK / CONTROVERSY
5. FUTURE / PREDICTION

Return ONLY valid JSON.

The response must be a JSON array containing exactly {count} objects.

Each object must use exactly these fields:

{{
    "angle": "The strategic angle used for this video.",
    "hook": "A compelling opening sentence.",
    "narration": "The complete spoken narration for a 30-60 second video.",
    "title": "A short attention-grabbing title.",
    "description": "A short description suitable for social media.",
    "cta": "A natural call to action."
}}

Requirements:

- Every package must be substantially different.
- Every factual claim must be supported by the supplied research.
- Do not invent facts, statistics, companies, studies, or quotes.
- "hook" must be designed to stop someone from scrolling.
- "narration" contains ONLY words that should actually be spoken aloud.
- Do NOT include labels such as HOOK, TITLE, DESCRIPTION, CTA,
  or ANGLE inside narration.
- Do NOT include markdown.
- Do NOT wrap the JSON in code fences.
- Do NOT include any text before or after the JSON.
- Narration should contain approximately 80-140 words.
"""

    content = ask_qwen_json(
        prompt
    )

    if not isinstance(content, list):
        raise RuntimeError(
            "Content generation did not return a JSON array."
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

        if not isinstance(package, dict):
            raise RuntimeError(
                f"Content package {index} "
                f"is not a JSON object."
            )

        missing = required_fields - package.keys()

        if missing:
            raise RuntimeError(
                f"Content package {index} "
                f"is missing fields: "
                f"{', '.join(sorted(missing))}"
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

    if not isinstance(visual_plan, dict):
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

    if not 3 <= len(visual_plan["scenes"]) <= 6:
        raise RuntimeError(
            "Visual plan must contain between "
            "3 and 6 scenes."
        )

    for index, scene in enumerate(
        visual_plan["scenes"],
        1,
    ):

        if not isinstance(scene, dict):
            raise RuntimeError(
                f"Visual scene {index} "
                "is not a JSON object."
            )

        required_fields = {
            "visual",
            "search",
            "duration",
        }

        missing = required_fields - scene.keys()

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