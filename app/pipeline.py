"""Single-video production entry point."""

import argparse
import json
from pathlib import Path

from app import pipeline_core
from app.editorial import normalize_and_dedupe_trends, prefilter_candidates
from app.job import create_run as _create_run
from app.publish_instagram import publish_video as publish_instagram_video
from app.publish_youtube import publish_video as publish_youtube_video
from app.research import ask_qwen_json
from app.topic_history import filter_covered_trends, load_topic_history
from app.trends import collect_trends


def _create_topic_run(_ignored: str) -> Path:
    """Create a run directory named after the selected topic."""
    topic = _create_topic_run.topic
    return _create_run(topic)


_create_topic_run.topic = ""  # type: ignore[attr-defined]


def _select_single_topic(trends):
    """Select one topic with one small Qwen call after cheap filtering."""
    history = load_topic_history()
    filtered_trends = filter_covered_trends(trends, history)
    candidates = normalize_and_dedupe_trends(filtered_trends)
    shortlist = prefilter_candidates(candidates, limit=8)

    print(f"   Deterministic prefilter: {len(candidates)} → {len(shortlist)} candidates.")

    if not shortlist:
        return []

    candidate_data = [
        {
            "candidate_id": candidate["candidate_id"],
            "title": candidate["title"],
            "source_titles": candidate["source_titles"],
            "urls": candidate["urls"],
        }
        for candidate in shortlist
    ]

    prompt = f"""
You are selecting ONE story for a faceless short-form video.

Candidate stories:
{json.dumps(candidate_data, indent=2, ensure_ascii=False)}

Choose the single strongest candidate for a short video.
Prioritize:
- curiosity
- surprise
- broad audience appeal
- clear story potential
- visual potential
- current relevance

Return ONLY valid JSON using exactly this structure:
{{
  "candidate_id": 0,
  "reason": "Brief reason this is the strongest candidate."
}}

Rules:
- candidate_id MUST exactly match one supplied candidate_id.
- Choose exactly ONE candidate.
- Do not invent facts.
- Do not invent URLs.
- Do not return markdown or code fences.
- Do not include anything outside the JSON object.
"""

    print("   Asking qwen3:8b for ONE topic selection...")
    selected = ask_qwen_json(prompt)

    if not isinstance(selected, dict):
        raise RuntimeError("Single-topic selection did not return a JSON object.")

    candidate_id = selected.get("candidate_id")
    if isinstance(candidate_id, str):
        try:
            candidate_id = int(candidate_id.strip())
        except ValueError:
            candidate_id = None

    selected_candidate = next(
        (candidate for candidate in shortlist if candidate["candidate_id"] == candidate_id),
        None,
    )

    if selected_candidate is None:
        raise RuntimeError("Single-topic selection returned an unknown candidate_id.")

    reason = selected.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "Selected as the strongest available short-form story opportunity."

    return [{
        "topic": selected_candidate["title"],
        "reason": reason.strip(),
        "category": selected_candidate["sources"][0].metadata.get("category", "other"),
        "source_indices": selected_candidate["source_indices"],
        "sources": selected_candidate["sources"],
    }]


def _publish_completed_videos(result, publish_instagram=True, publish_youtube=True):
    """Publish completed videos to selected platforms without affecting production success."""
    completed_videos = result.get("completed_videos", [])

    if not completed_videos:
        return

    for video_path in completed_videos:
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


def run_single(
    mode: str = "publish",
    cancellation_event=None,
    status_callback=None,
    publish_instagram: bool = True,
    publish_youtube: bool = True,
):
    """Discover, select, produce, and publish exactly one video."""
    print("\n================================")
    print("🎯 SINGLE-VIDEO PIPELINE")
    print("================================")

    if cancellation_event is not None and cancellation_event.is_set():
        raise pipeline_core.PipelineCancelled()

    print("\n📡 Collecting current trends...")
    trends = collect_trends(hackernews_limit=20)
    if not trends:
        raise RuntimeError("No current trends were collected.")

    if cancellation_event is not None and cancellation_event.is_set():
        raise pipeline_core.PipelineCancelled()

    print("\n🧠 Selecting one topic...")
    print(f"   Raw candidates: {len(trends)}")
    topics = _select_single_topic(trends)
    if not topics:
        raise RuntimeError("No viable trending topic was selected.")

    selected_topic = topics[0]
    topic = selected_topic["topic"]
    print(f"\n🎯 Selected topic: {topic}")
    print("   Run directory will use the topic slug.")

    _create_topic_run.topic = topic
    original_create_run = pipeline_core.create_run
    pipeline_core.create_run = _create_topic_run

    try:
        result = pipeline_core.run_pipeline(
            content_count=1,
            selected_topics=[selected_topic],
            mode=mode,
            cancellation_event=cancellation_event,
            status_callback=status_callback,
            selection_diagnostics={
                "raw_trend_count": len(trends),
                "single_video_selection": True,
            },
        )
    finally:
        pipeline_core.create_run = original_create_run

    if mode == "publish":
        _publish_completed_videos(result, publish_instagram, publish_youtube)

    return result


def main():
    parser = argparse.ArgumentParser(description="Run the single-video Content Engine pipeline.")
    parser.add_argument("--noinstagram", action="store_true", help="Skip Instagram publishing.")
    parser.add_argument("--noyoutube", action="store_true", help="Skip YouTube publishing.")
    args = parser.parse_args()

    run_single(
        publish_instagram=not args.noinstagram,
        publish_youtube=not args.noyoutube,
    )


if __name__ == "__main__":
    main()
