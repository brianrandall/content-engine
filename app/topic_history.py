from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import re


BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_PATH = BASE_DIR / "output" / "topic_history.json"


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def load_topic_history(
    path: Path = HISTORY_PATH,
):
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as file:
            history = json.load(file)
    except (OSError, json.JSONDecodeError):
        return []

    return history if isinstance(history, list) else []


def _matches_history(
    title: str,
    history: list[dict],
):
    normalized_title = _normalize(title)

    if not normalized_title:
        return False

    for entry in history:
        if not isinstance(entry, dict):
            continue

        candidates = [
            entry.get("topic", ""),
            *entry.get("source_titles", []),
        ]

        for candidate in candidates:
            normalized_candidate = _normalize(candidate)

            if not normalized_candidate:
                continue

            if normalized_title == normalized_candidate:
                return True

            if SequenceMatcher(
                None,
                normalized_title,
                normalized_candidate,
            ).ratio() >= 0.88:
                return True

    return False


def filter_covered_trends(
    trends,
    history: list[dict] | None = None,
):
    if history is None:
        history = load_topic_history()

    return [
        trend
        for trend in trends
        if not _matches_history(
            trend.title,
            history,
        )
    ]


def recent_topics(
    history: list[dict] | None = None,
    limit: int = 20,
):
    if history is None:
        history = load_topic_history()

    return [
        entry["topic"]
        for entry in reversed(history)
        if isinstance(entry, dict)
        and isinstance(entry.get("topic"), str)
        and entry["topic"].strip()
    ][:limit]


def record_topics(
    topics,
    path: Path = HISTORY_PATH,
):
    history = load_topic_history(path)
    recorded_at = datetime.now(timezone.utc).isoformat()

    for topic in topics:
        sources = topic.get("sources", [])
        history.append(
            {
                "topic": topic.get("topic", ""),
                "source_titles": [
                    source.title
                    for source in sources
                    if hasattr(source, "title")
                ],
                "recorded_at": recorded_at,
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(
            history,
            file,
            indent=2,
            ensure_ascii=False,
        )
