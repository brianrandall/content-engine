from difflib import SequenceMatcher
from datetime import datetime, timezone
import json
import re

from app.research import ask_qwen_json


MAX_VIDEOS = 8
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
        len(left_words),
        len(right_words),
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
You are evaluating every candidate story for a short-form video
editorial slate. Evaluate every supplied candidate independently.
Do not select a final list. Do not return prose outside JSON.

The target slate has up to {count} stories, but every candidate
must receive an evaluation so Python can construct the final slate.

Candidates:
{json.dumps(candidate_data, indent=2, ensure_ascii=False)}

For each candidate, return exactly one object in a JSON array with:
- candidate_id: the supplied candidate_id
- category: one of science, technology, business, entertainment,
  culture, politics, world, history, internet, human-interest,
  sports, other
- timeliness: integer 0-100
- current_momentum: integer 0-100
- curiosity: integer 0-100
- surprise: integer 0-100
- broad_appeal: integer 0-100
- human_interest: integer 0-100
- conflict_or_stakes: integer 0-100
- visual_potential: integer 0-100
- storytelling_potential: integer 0-100
- researchability: integer 0-100
- recommended: boolean
- confidence: integer 0-100
- brief_reason: concise evidence-based reason

Score only what the supplied candidate data supports. Penalize stale
news, weak source material, poor standalone video potential, and
stories that are merely generic facts or discussions. Favor timely,
current, surprising, broad-audience stories with strong hooks,
visual potential, and credible research potential. Never invent facts.
"""


def _valid_score(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100


def _recommendation_bonus(evaluation):
    if not evaluation["recommended"]:
        return 0

    return round(
        RECOMMENDATION_BONUS_MAX
        * evaluation["confidence"]
        / 100,
        2,
    )


def validate_evaluations(raw_evaluations, candidates):
    if isinstance(raw_evaluations, dict):
        raw_evaluations = raw_evaluations.get("evaluations")

    if not isinstance(raw_evaluations, list):
        raise RuntimeError("Editorial evaluation did not return a JSON array.")

    candidates_by_id = {
        candidate["candidate_id"]: candidate
        for candidate in candidates
    }
    evaluations = []
    seen_candidate_ids = set()

    for evaluation in raw_evaluations:
        if not isinstance(evaluation, dict):
            continue

        candidate_id = evaluation.get("candidate_id")
        candidate = candidates_by_id.get(candidate_id)
        category = evaluation.get("category")

        if candidate is None or category not in ALLOWED_CATEGORIES:
            continue

        if candidate_id in seen_candidate_ids:
            continue

        if any(
            not _valid_score(evaluation.get(field))
            for field in SCORE_FIELDS
        ):
            continue

        if not isinstance(evaluation.get("recommended"), bool):
            continue

        confidence = evaluation.get("confidence")
        if not _valid_score(confidence):
            continue

        reason = evaluation.get("brief_reason")
        if not isinstance(reason, str) or not reason.strip():
            continue

        opportunity_score = round(
            sum(
                evaluation[field] * weight
                for field, weight in SCORE_WEIGHTS.items()
            ),
            2,
        )

        evaluations.append(
            {
                **evaluation,
                "brief_reason": reason.strip(),
                "opportunity_score": opportunity_score,
                "candidate": candidate,
            }
        )
        seen_candidate_ids.add(candidate_id)

    return evaluations


def build_editorial_slate(evaluations, count=MAX_VIDEOS):
    remaining = list(evaluations)
    selected = []
    category_counts = {}

    while remaining and len(selected) < count:
        unused = [
            e for e in remaining
            if category_counts.get(e["category"], 0) == 0
        ]

        if unused:
            pool = unused
        else:
            eligible = [
                e for e in remaining
                if category_counts.get(e["category"], 0) < 2
            ]

            pool = eligible if eligible else remaining

        best_index = None
        best_score = None

        for index, evaluation in enumerate(pool):
            category = evaluation["category"]
            occurrence = category_counts.get(category, 0)

            penalty = CATEGORY_REPETITION_PENALTIES[
                min(
                    occurrence,
                    len(CATEGORY_REPETITION_PENALTIES) - 1,
                )
            ]

            recommendation_bonus = _recommendation_bonus(evaluation)

            adjusted_score = round(
                evaluation["opportunity_score"]
                + recommendation_bonus
                - penalty,
                2,
            )

            if (
                best_score is None
                or adjusted_score > best_score
                or (
                    adjusted_score == best_score
                    and evaluation["candidate"]["candidate_id"]
                    < pool[best_index]["candidate"]["candidate_id"]
                )
            ):
                best_index = index
                best_score = adjusted_score

        evaluation = pool[best_index]
        remaining.remove(evaluation)

        category = evaluation["category"]
        category_counts[category] = (
            category_counts.get(category, 0) + 1
        )

        candidate = evaluation["candidate"]

        selected.append(
            {
                "topic": candidate["title"],
                "reason": evaluation["brief_reason"],
                "category": category,
                "source_indices": candidate["source_indices"],
                "sources": candidate["sources"],
                "opportunity_score": evaluation["opportunity_score"],
                "recommendation_bonus": _recommendation_bonus(
                    evaluation
                ),
                "adjusted_score": best_score,
                "selection_rationale": (
                    "Selected by weighted editorial score with "
                    f"{category_counts[category] - 1} prior "
                    f"{category} story penalty."
                ),
            }
        )

    return selected, category_counts


def evaluate_and_select(trends, count=MAX_VIDEOS):
    candidates = normalize_and_dedupe_trends(trends)
    if not candidates:
        return [], {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_trend_count": len(trends),
            "normalized_candidate_count": 0,
            "evaluated_candidate_count": 0,
            "category_distribution": {},
            "evaluations": [],
        }

    raw_evaluations = ask_qwen_json(
        build_evaluation_prompt(candidates, count)
    )
    evaluations = validate_evaluations(raw_evaluations, candidates)
    topics, category_distribution = build_editorial_slate(
        evaluations,
        count,
    )

    diagnostics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "raw_trend_count": len(trends),
        "normalized_candidate_count": len(candidates),
        "evaluated_candidate_count": len(evaluations),
        "category_distribution": category_distribution,
        "evaluations": [
            {
                key: value
                for key, value in evaluation.items()
                if key != "candidate"
            }
            for evaluation in evaluations
        ],
    }
    return topics, diagnostics
