from difflib import SequenceMatcher
from datetime import datetime, timezone
import json
import re

from app.research import ask_qwen_json


MAX_VIDEOS = 8

# qwen3:8b is much more reliable when the editorial pass is
# split into small batches. Keep this at 12 for output quality.
EVALUATION_BATCH_SIZE = 12

# Do not make the local model read every collected headline.
# A deterministic prefilter reduces the normal 100+ candidate
# corpus to a manageable editorial shortlist first.
MAX_EDITORIAL_CANDIDATES = 60

CATEGORY_REPETITION_PENALTIES = (0, 6, 14, 24, 36, 50)
RECOMMENDATION_BONUS_MAX = 5

SCORE_WEIGHTS = {
    "timeliness": 0.16,
    "current_momentum": 0.10,
    "curiosity": 0.14,
    "surprise": 0.10,
    "broad_appeal": 0.14,
    "human_interest": 0.06,
    "conflict_or_stakes": 0.08,
    "visual_potential": 0.10,
    "storytelling_potential": 0.07,
    "researchability": 0.05,
}

ALLOWED_CATEGORIES = {
    "science",
    "technology",
    "business",
    "entertainment",
    "culture",
    "politics",
    "world",
    "history",
    "internet",
    "human-interest",
    "sports",
    "other",
}

SCORE_FIELDS = tuple(SCORE_WEIGHTS)


# =========================================================
# NORMALIZATION / PREFILTER
# =========================================================

def normalize_title(title: str) -> str:
    title = title.casefold()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return " ".join(title.split())


def _obvious_duplicate(left: str, right: str) -> bool:
    left_normalized = normalize_title(left)
    right_normalized = normalize_title(right)

    if left_normalized == right_normalized:
        return True

    left_words = set(left_normalized.split())
    right_words = set(right_normalized.split())

    if not left_words or not right_words:
        return False

    overlap = len(left_words & right_words) / min(
        len(left_words), len(right_words)
    )

    return (
        overlap >= 0.9
        and SequenceMatcher(
            None,
            left_normalized,
            right_normalized,
        ).ratio() >= 0.82
    )


def normalize_and_dedupe_trends(trends):
    """Convert TrendItems into unique editorial candidates."""
    candidates = []

    for source_index, trend in enumerate(trends):
        matching_candidate = None

        for candidate in candidates:
            if _obvious_duplicate(
                trend.title,
                candidate["title"],
            ):
                matching_candidate = candidate
                break

        if matching_candidate is None:
            candidates.append(
                {
                    "candidate_id": len(candidates),
                    "title": trend.title,
                    "source_indices": [source_index],
                    "source_titles": [trend.title],
                    "urls": [trend.url] if trend.url else [],
                    "sources": [trend],
                }
            )
        else:
            matching_candidate["source_indices"].append(source_index)
            matching_candidate["source_titles"].append(trend.title)
            if trend.url:
                matching_candidate["urls"].append(trend.url)
            matching_candidate["sources"].append(trend)

    return candidates


def _prefilter_score(candidate):
    """Cheap deterministic score used before local-LLM evaluation."""
    title = candidate["title"]
    normalized = title.casefold()

    score = 0.0

    # Multiple independent sources are a useful momentum signal.
    score += min(len(candidate["sources"]), 5) * 8

    # Prefer current-news sources slightly over discussion aggregators.
    source_names = {
        source.source
        for source in candidate["sources"]
    }
    if "google_news" in source_names:
        score += 12
    if "reddit" in source_names:
        score += 4
    if "hackernews" in source_names:
        score += 3

    # Headline characteristics that tend to make strong short-form hooks.
    curiosity_terms = (
        "dies", "dead", "approves", "bans", "leaks", "leaked",
        "crisis", "warning", "warn", "surge", "breakthrough",
        "discovery", "reveals", "revealed", "secret", "first",
        "new", "major", "historic", "mass", "record", "shocking",
        "unexpected", "billions", "lawsuit", "settlement", "attack",
    )
    for term in curiosity_terms:
        if re.search(r"\b" + re.escape(term) + r"\b", normalized):
            score += 2

    # Extremely short headlines generally contain less usable context.
    word_count = len(normalized.split())
    if 7 <= word_count <= 22:
        score += 6
    elif word_count < 4:
        score -= 5

    return score


def prefilter_candidates(candidates, limit=MAX_EDITORIAL_CANDIDATES):
    """Reduce the raw editorial corpus without using an LLM."""
    if len(candidates) <= limit:
        return candidates

    ranked = sorted(
        candidates,
        key=lambda candidate: (
            _prefilter_score(candidate),
            -candidate["candidate_id"],
        ),
        reverse=True,
    )

    selected = ranked[:limit]

    # Preserve original candidate ordering so diagnostics remain easy to read.
    selected.sort(key=lambda candidate: candidate["candidate_id"])
    return selected


# =========================================================
# QWEN EVALUATION
# =========================================================

def build_evaluation_prompt(candidates, count):
    candidate_data = [
        {
            "candidate_id": candidate["candidate_id"],
            "title": candidate["title"],
            "source_titles": candidate["source_titles"],
            "urls": candidate["urls"],
        }
        for candidate in candidates
    ]

    return f"""
You are evaluating candidate stories for a short-form video editorial system.

Evaluate EVERY candidate below independently.

There are {len(candidates)} candidates in this batch.
The final production slate contains up to {count} stories.
Do NOT select the final slate here.

Candidates:
{json.dumps(candidate_data, indent=2, ensure_ascii=False)}

Return ONLY a JSON array with EXACTLY one object for every supplied candidate.

Each object MUST contain:
{{
  "candidate_id": 0,
  "category": "science",
  "timeliness": 0,
  "current_momentum": 0,
  "curiosity": 0,
  "surprise": 0,
  "broad_appeal": 0,
  "human_interest": 0,
  "conflict_or_stakes": 0,
  "visual_potential": 0,
  "storytelling_potential": 0,
  "researchability": 0,
  "recommended": false,
  "confidence": 0,
  "brief_reason": "Brief reason"
}}

All score fields and confidence must be integers from 0 to 100.

Score:
timeliness = how current/recent the story appears.
current_momentum = apparent current attention.
curiosity = desire to know more.
surprise = unexpectedness or unusualness.
broad_appeal = breadth of potential audience.
human_interest = emotional or human interest.
conflict_or_stakes = consequences, disagreement, risk, conflict, or stakes.
visual_potential = ease of representing the story with compelling visuals.
storytelling_potential = ease of turning the story into a coherent short narrative.
researchability = likelihood of finding enough credible material for later research.
recommended = true when especially suitable for short-form production.
confidence = confidence in this evaluation based ONLY on the supplied candidate.

Allowed categories:
science, technology, business, entertainment, culture, politics, world,
history, internet, human-interest, sports, other

Classify the STORY SUBJECT, not the publisher.

Examples:
FDA pancreatic cancer drug -> science
Nvidia earnings -> business
Government cease-fire -> politics
AI model release -> technology
Celebrity movie announcement -> entertainment

IMPORTANT:
- Use the candidate_id EXACTLY as supplied.
- Do not invent facts or information.
- Do not use publisher identity to determine category.
- Do not return markdown.
- Do not return code fences.
- Do not include explanations outside the JSON array.
- Return one evaluation object for every candidate you can evaluate.
"""


# =========================================================
# VALIDATION
# =========================================================

def _valid_score(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= 100
    if isinstance(value, float) and value.is_integer():
        return 0 <= int(value) <= 100
    return False


def _coerce_score(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 100 else None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
        return value if 0 <= value <= 100 else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        if parsed.is_integer() and 0 <= parsed <= 100:
            return int(parsed)
    return None


def _coerce_candidate_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_recommended(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


def _normalize_raw_evaluations(raw_evaluations):
    """Accept the common JSON shapes Qwen may return."""
    if isinstance(raw_evaluations, list):
        return raw_evaluations

    if not isinstance(raw_evaluations, dict):
        return []

    for key in ("evaluations", "results", "items", "data"):
        value = raw_evaluations.get(key)
        if isinstance(value, list):
            return value

    # Also tolerate an object keyed by candidate id.
    values = []
    for key, value in raw_evaluations.items():
        if isinstance(value, dict):
            item = dict(value)
            item.setdefault("candidate_id", key)
            values.append(item)
    return values


def validate_evaluations(raw_evaluations, candidates):
    """Keep valid individual evaluations instead of rejecting an entire batch."""
    raw_evaluations = _normalize_raw_evaluations(raw_evaluations)

    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in candidates
    }

    evaluations = []
    seen_candidate_ids = set()

    for raw in raw_evaluations:
        if not isinstance(raw, dict):
            continue

        candidate_id = _coerce_candidate_id(raw.get("candidate_id"))
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None or candidate_id in seen_candidate_ids:
            continue

        category = raw.get("category")
        if isinstance(category, str):
            category = category.strip().casefold()
        if category not in ALLOWED_CATEGORIES:
            continue

        normalized = dict(raw)
        normalized["candidate_id"] = candidate_id
        normalized["category"] = category

        invalid = False
        for field in SCORE_FIELDS:
            score = _coerce_score(raw.get(field))
            if score is None:
                invalid = True
                break
            normalized[field] = score
        if invalid:
            continue

        recommended = _coerce_recommended(raw.get("recommended"))
        if recommended is None:
            continue
        normalized["recommended"] = recommended

        confidence = _coerce_score(raw.get("confidence"))
        if confidence is None:
            continue
        normalized["confidence"] = confidence

        reason = raw.get("brief_reason")
        if not isinstance(reason, str) or not reason.strip():
            reason = "Strong candidate based on the supplied headline and source context."
        normalized["brief_reason"] = reason.strip()

        normalized["opportunity_score"] = round(
            sum(normalized[field] * weight for field, weight in SCORE_WEIGHTS.items()),
            2,
        )
        normalized["candidate"] = candidate

        evaluations.append(normalized)
        seen_candidate_ids.add(candidate_id)

    return evaluations


def _recommendation_bonus(evaluation):
    if not evaluation["recommended"]:
        return 0
    return round(
        RECOMMENDATION_BONUS_MAX * evaluation["confidence"] / 100,
        2,
    )


# =========================================================
# EDITORIAL SLATE
# =========================================================

def build_editorial_slate(evaluations, count=MAX_VIDEOS):
    remaining = list(evaluations)
    selected = []
    category_counts = {}

    while remaining and len(selected) < count:
        unused = [
            evaluation
            for evaluation in remaining
            if category_counts.get(evaluation["category"], 0) == 0
        ]
        pool = unused if unused else [
            evaluation
            for evaluation in remaining
            if category_counts.get(evaluation["category"], 0) < 2
        ]
        if not pool:
            pool = remaining

        best_index = None
        best_score = None

        for index, evaluation in enumerate(pool):
            category = evaluation["category"]
            occurrence = category_counts.get(category, 0)
            penalty = CATEGORY_REPETITION_PENALTIES[
                min(occurrence, len(CATEGORY_REPETITION_PENALTIES) - 1)
            ]
            adjusted_score = round(
                evaluation["opportunity_score"]
                + _recommendation_bonus(evaluation)
                - penalty,
                2,
            )

            candidate_id = evaluation["candidate"]["candidate_id"]
            best_candidate_id = (
                pool[best_index]["candidate"]["candidate_id"]
                if best_index is not None
                else None
            )

            if (
                best_score is None
                or adjusted_score > best_score
                or (
                    adjusted_score == best_score
                    and candidate_id < best_candidate_id
                )
            ):
                best_index = index
                best_score = adjusted_score

        evaluation = pool[best_index]
        remaining.remove(evaluation)

        category = evaluation["category"]
        category_counts[category] = category_counts.get(category, 0) + 1
        candidate = evaluation["candidate"]

        selected.append(
            {
                "topic": candidate["title"],
                "reason": evaluation["brief_reason"],
                "category": category,
                "source_indices": candidate["source_indices"],
                "sources": candidate["sources"],
                "opportunity_score": evaluation["opportunity_score"],
                "recommendation_bonus": _recommendation_bonus(evaluation),
                "adjusted_score": best_score,
                "selection_rationale": (
                    "Selected by weighted editorial score with "
                    f"{category_counts[category] - 1} prior {category} story penalty."
                ),
            }
        )

    return selected, category_counts


# =========================================================
# MAIN EDITORIAL EVALUATION
# =========================================================

def evaluate_and_select(trends, count=MAX_VIDEOS):
    """Evaluate a reduced candidate set and select the strongest slate."""
    candidates = normalize_and_dedupe_trends(trends)
    prefiltered_candidates = prefilter_candidates(candidates)

    diagnostics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_trend_count": len(trends),
        "normalized_candidate_count": len(candidates),
        "prefiltered_candidate_count": len(prefiltered_candidates),
        "max_editorial_candidates": MAX_EDITORIAL_CANDIDATES,
        "evaluated_candidate_count": 0,
        "evaluation_batch_size": EVALUATION_BATCH_SIZE,
        "evaluation_batch_count": 0,
        "failed_batches": [],
        "category_distribution": {},
        "evaluations": [],
    }

    if not prefiltered_candidates:
        return [], diagnostics

    total_batches = (
        len(prefiltered_candidates) + EVALUATION_BATCH_SIZE - 1
    ) // EVALUATION_BATCH_SIZE
    diagnostics["evaluation_batch_count"] = total_batches

    print(
        f"   🧠 Evaluating {len(prefiltered_candidates)} candidates "
        f"in {total_batches} batches..."
    )

    if len(prefiltered_candidates) < len(candidates):
        print(
            f"   ⚡ Deterministic prefilter: {len(candidates)} → "
            f"{len(prefiltered_candidates)} candidates before Qwen."
        )

    all_evaluations = []

    for batch_number, start in enumerate(
        range(0, len(prefiltered_candidates), EVALUATION_BATCH_SIZE),
        1,
    ):
        batch = prefiltered_candidates[start:start + EVALUATION_BATCH_SIZE]

        print(
            f"   🤖 Editorial batch {batch_number}/{total_batches} "
            f"({len(batch)} candidates)..."
        )

        try:
            raw_evaluations = ask_qwen_json(
                build_evaluation_prompt(batch, count)
            )
            evaluations = validate_evaluations(raw_evaluations, batch)

            if not evaluations:
                # One focused retry is worthwhile only when the entire
                # batch was unusable. The retry asks for less prose and
                # makes the required IDs/schema especially explicit.
                print("      ⚠️ Batch returned no valid evaluations; retrying focused pass...")
                retry_prompt = build_evaluation_prompt(batch, count) + "\nReturn compact JSON. Do not omit any candidate_id."
                raw_retry = ask_qwen_json(retry_prompt)
                evaluations = validate_evaluations(raw_retry, batch)

            if not evaluations:
                print("      ⚠️ Batch still returned no valid evaluations.")
                diagnostics["failed_batches"].append(
                    {
                        "batch": batch_number,
                        "candidate_ids": [c["candidate_id"] for c in batch],
                        "reason": "No valid evaluations returned after focused retry.",
                    }
                )
                continue

            print(
                f"      ✅ {len(evaluations)}/{len(batch)} evaluations"
            )
            all_evaluations.extend(evaluations)

        except Exception as exc:
            print(
                f"      ⚠️ Editorial batch failed: "
                f"{type(exc).__name__}: {exc}"
            )
            diagnostics["failed_batches"].append(
                {
                    "batch": batch_number,
                    "candidate_ids": [c["candidate_id"] for c in batch],
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    if not all_evaluations:
        print("   ⚠️ No editorial evaluations were produced.")
        return [], diagnostics

    unique_evaluations = {}
    for evaluation in all_evaluations:
        unique_evaluations[evaluation["candidate"]["candidate_id"]] = evaluation
    all_evaluations = list(unique_evaluations.values())

    topics, category_distribution = build_editorial_slate(
        all_evaluations,
        count,
    )

    diagnostics["evaluated_candidate_count"] = len(all_evaluations)
    diagnostics["category_distribution"] = category_distribution
    diagnostics["evaluations"] = [
        {
            key: value
            for key, value in evaluation.items()
            if key != "candidate"
        }
        for evaluation in all_evaluations
    ]

    print(
        f"   ✅ Evaluated {len(all_evaluations)}/"
        f"{len(prefiltered_candidates)} candidates."
    )
    print(f"   🎯 Selected {len(topics)} editorial topics.")

    return topics, diagnostics
