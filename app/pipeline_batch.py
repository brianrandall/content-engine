"""Morning batch production entry point."""

import argparse
import json
import re
from pathlib import Path

from app import pipeline_core
from app.job import create_run as _create_run
from app.publish_instagram import publish_video as publish_instagram_video
from app.publish_youtube import publish_video as publish_youtube_video
from app.research import ask_qwen_json
from app.trends import collect_trends
from app.editorial import normalize_and_dedupe_trends, prefilter_candidates
from app.topic_history import filter_covered_trends, load_topic_history


BATCH_COUNT = 4
SELECTION_POOL_SIZE = 12

TECH_HEADLINE_PATTERNS = (
    r"\bai\b", r"\bartificial intelligence\b", r"\bmachine learning\b",
    r"\bllm\b", r"\bchatgpt\b", r"\bopenai\b", r"\bclaude\b",
    r"\bgemini\b", r"\bnvidia\b", r"\bapple\b", r"\biphone\b",
    r"\bgoogle\b", r"\bmicrosoft\b", r"\bmeta\b", r"\bamazon\b",
    r"\btesla\b", r"\bsoftware\b", r"\bcyber\b", r"\bhacker\b",
    r"\brobot\b", r"\brobotics\b", r"\bsemiconductor\b", r"\bchip(s)?\b",
    r"\bgpu(s)?\b", r"\btech(nology)?\b", r"\bstartup(s)?\b",
)


def _create_batch_run(_ignored: str) -> Path:
    """Create a run directory explicitly labeled as the batch."""
    return _create_run("batch")


def _candidate_payload(candidates):
    return [
        {"candidate_id": c["candidate_id"], "title": c["title"],
         "source_titles": c["source_titles"], "urls": c["urls"]}
        for c in candidates
    ]


def _is_tech_candidate(candidate):
    """Hard-cap technology-related stories at one per morning batch."""
    for source in candidate.get("sources", []):
        metadata = getattr(source, "metadata", {}) or {}
        if str(metadata.get("category", "")).casefold() in {"technology", "internet"}:
            return True
    title = candidate.get("title", "").casefold()
    return any(re.search(pattern, title, re.IGNORECASE) for pattern in TECH_HEADLINE_PATTERNS)


def _select_one_topic(candidates, selected_titles):
    """Use one small Qwen call to select exactly one candidate."""
    prompt = f"""
You are selecting ONE story for a faceless short-form video.

Candidates:
{json.dumps(_candidate_payload(candidates), indent=2, ensure_ascii=False)}

Already selected for this batch:
{json.dumps(selected_titles, ensure_ascii=False)}

Select the single strongest remaining story.

Prioritize:
- current relevance
- curiosity
- broad audience appeal
- surprising or consequential subject matter
- visual storytelling potential
- enough substance to research

Return ONLY valid JSON using exactly this structure:
{{
  "candidate_id": 0,
  "reason": "Brief reason this is the strongest remaining story."
}}

Rules:
- candidate_id MUST exactly match one supplied candidate_id.
- Do not select a story already listed in Already selected.
- Do not invent facts.
- Do not invent URLs.
- Return only JSON. No markdown. No code fences. No explanation outside JSON.
"""
    result = ask_qwen_json(prompt)
    if not isinstance(result, dict):
        raise RuntimeError("Batch topic selection did not return an object.")

    candidate_id = result.get("candidate_id")
    if isinstance(candidate_id, str):
        try:
            candidate_id = int(candidate_id.strip())
        except ValueError as exc:
            raise RuntimeError("Batch topic selector returned an invalid candidate_id.") from exc
    if not isinstance(candidate_id, int):
        raise RuntimeError("Batch topic selector returned an invalid candidate_id.")

    selected = next((c for c in candidates if c["candidate_id"] == candidate_id), None)
    if selected is None:
        raise RuntimeError(f"Batch topic selector returned unknown candidate_id {candidate_id}.")
    return selected


def _publish_completed_videos(result, publish_instagram=True, publish_youtube=True):
    """Publish completed videos to selected platforms without affecting production success."""
    for video_path in result.get("completed_videos", []):
        if publish_instagram:
            try:
                publish_instagram_video(video_path)
            except Exception as exc:
                print("\n⚠️ Instagram publishing failed after video production:")
                print(f"   {type(exc).__name__}: {exc}")
                print("   The video remains successfully produced and can be published separately.")
        if publish_youtube:
            try:
                publish_youtube_video(video_path)
            except Exception as exc:
                print("\n⚠️ YouTube publishing failed after video production:")
                print(f"   {type(exc).__name__}: {exc}")
                print("   The video remains successfully produced and can be published separately.")


def _build_batch_topics(trends, count=BATCH_COUNT):
    """Build a four-story slate with four lightweight Qwen calls."""
    history = load_topic_history()
    uncovered = filter_covered_trends(trends, history)
    if not uncovered:
        raise RuntimeError("No uncovered trends available for batch production.")

    candidates = normalize_and_dedupe_trends(uncovered)
    candidates = prefilter_candidates(candidates, limit=max(SELECTION_POOL_SIZE, count * 3))
    print(f"   Deterministic prefilter: {len(uncovered)} → {len(candidates)} candidates.")
    print(f"   Making {count} lightweight Qwen selections (one per video)...")

    selected = []
    selected_titles = []
    remaining = list(candidates)
    tech_selected = False

    for index in range(1, count + 1):
        if not remaining:
            break
        eligible = ([c for c in remaining if not _is_tech_candidate(c)]
                    if tech_selected else remaining)
        if not eligible:
            raise RuntimeError("Batch topic selection exhausted non-technology candidates before reaching the requested batch size.")

        pool = eligible[:SELECTION_POOL_SIZE]
        print(f"   Topic selection {index}/{count} ({len(pool)} candidates)...")
        candidate = _select_one_topic(pool, selected_titles)
        is_tech = _is_tech_candidate(candidate)
        if is_tech and tech_selected:
            raise RuntimeError("Technology-topic cap violated: selector returned a second tech story.")
        if is_tech:
            tech_selected = True
            print("      [tech cap] Technology story selected; remaining selections exclude tech.")

        selected_titles.append(candidate["title"])
        selected.append({
            "topic": candidate["title"],
            "reason": "Selected by lightweight batch topic selection.",
            "category": "technology" if is_tech else "other",
            "source_indices": candidate["source_indices"],
            "sources": candidate["sources"],
        })
        remaining = [item for item in remaining if item["candidate_id"] != candidate["candidate_id"]]
        print(f"      {candidate['title']}")

    if len(selected) != count:
        raise RuntimeError(f"Expected {count} batch topics, received {len(selected)}.")
    return selected


def run_batch(content_count=BATCH_COUNT, mode="publish", cancellation_event=None,
              status_callback=None, publish_instagram=True, publish_youtube=True):
    """Produce the morning batch, defaulting to four videos."""
    if content_count != BATCH_COUNT:
        raise ValueError("The morning batch is intentionally fixed at 4 videos.")
    if mode not in ("publish", "local"):
        raise ValueError("mode must be 'publish' or 'local'.")

    print("\n================================")
    print("🎯 MORNING BATCH PIPELINE")
    print("================================")
    print(f"Videos: {BATCH_COUNT}")

    if cancellation_event is not None and cancellation_event.is_set():
        raise pipeline_core.PipelineCancelled()

    print("\n📡 Collecting current trends ONCE...")
    trends = collect_trends(hackernews_limit=20)
    if not trends:
        raise RuntimeError("No current trends were collected.")
    print(f"Found {len(trends)} trends.")
    print("\n🧠 Selecting four topics...")

    topics = _build_batch_topics(trends, count=BATCH_COUNT)
    print("\nSelected 4 topics.")
    for index, topic in enumerate(topics, 1):
        print(f"   {index}. {topic['topic']}")

    original_create_run = pipeline_core.create_run
    pipeline_core.create_run = _create_batch_run
    try:
        result = pipeline_core.run_pipeline(
            content_count=BATCH_COUNT,
            selected_topics=topics,
            mode=mode,
            cancellation_event=cancellation_event,
            status_callback=status_callback,
        )
    finally:
        pipeline_core.create_run = original_create_run

    if mode == "publish":
        _publish_completed_videos(result, publish_instagram, publish_youtube)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run the four-video morning Content Engine batch.")
    parser.add_argument("--noinstagram", action="store_true", help="Skip Instagram publishing.")
    parser.add_argument("--noyoutube", action="store_true", help="Skip YouTube publishing.")
    args = parser.parse_args()
    run_batch(
        publish_instagram=not args.noinstagram,
        publish_youtube=not args.noyoutube,
    )


if __name__ == "__main__":
    main()
