import json
import asyncio
import inspect
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import pipeline, trends
from app import main
from app.topic_history import (
    filter_covered_trends,
    record_topics,
)


class TopicPipelineTests(unittest.TestCase):
    def make_topic(self, item, topic="Story", category="world"):
        return {
            "topic": topic,
            "reason": "This is worth covering.",
            "category": category,
            "source_indices": [0],
            "sources": [item],
        }

    def test_rank_skips_invalid_indices_and_allows_fewer_topics(self):
        items = [trends.TrendItem("news", "A"), trends.TrendItem("news", "B")]
        response = [
            self.make_topic(items[0], "Valid one"),
            {
                "topic": "Invalid one",
                "reason": "Reason",
                "category": "world",
                "source_indices": [99],
            },
            {
                "topic": "Malformed one",
                "reason": "Reason",
                "category": "world",
                "source_indices": [[0]],
            },
        ]

        with patch("app.topic_history.load_topic_history", return_value=[]), \
             patch("app.trends.ask_qwen_json", return_value=response):
            result = trends.rank_trending_topics(items, count=5)

        self.assertEqual([topic["topic"] for topic in result], ["Valid one"])
        self.assertIs(result[0]["sources"][0], items[0])

    def test_rank_defaults_to_eight_topics(self):
        self.assertEqual(
            inspect.signature(trends.rank_trending_topics)
            .parameters["count"].default,
            8,
        )

    def test_rank_skips_missing_fields(self):
        item = trends.TrendItem("news", "A")
        response = [
            {"topic": "Malformed"},
            self.make_topic(item, "Valid"),
        ]

        with patch("app.topic_history.load_topic_history", return_value=[]), \
             patch("app.trends.ask_qwen_json", return_value=response):
            result = trends.rank_trending_topics([item], count=8)

        self.assertEqual([topic["topic"] for topic in result], ["Valid"])

    def test_rank_rejects_duplicates_and_includes_category_guidance(self):
        item = trends.TrendItem("news", "A")
        response = [
            self.make_topic(item, "Same story", "sports"),
            self.make_topic(item, "Same story", "world"),
            {
                "topic": "Bad category",
                "reason": "Reason",
                "category": "food",
                "source_indices": [0],
            },
        ]

        with patch("app.topic_history.load_topic_history", return_value=[]), \
             patch("app.trends.ask_qwen_json", return_value=response) as ask:
            result = trends.rank_trending_topics([item], count=5)

        prompt = ask.call_args.args[0]
        self.assertIn("sports", prompt)
        self.assertIn("Five sports stories are acceptable only if", prompt)
        self.assertEqual(len(result), 1)

    def test_history_only_excludes_completed_topics(self):
        item = trends.TrendItem("news", "Covered headline")
        topic = self.make_topic(item, "Covered headline")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topic_history.json"
            record_topics([topic], path, status="failed")
            history = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(filter_covered_trends([item], history), [item])

            record_topics([topic], path, status="completed")
            history = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(history), 2)
            self.assertEqual(filter_covered_trends([item], history), [])

    def test_pipeline_uses_explicit_topics_without_collecting(self):
        item = trends.TrendItem("news", "Selected")
        selected = [self.make_topic(item, "Selected")]

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            final_video = run_dir / "final_short.mp4"
            final_video.touch()

            with patch.object(pipeline, "create_run", return_value=run_dir), \
                  patch("app.trends.collect_trends") as collect, \
                  patch("app.trends.rank_trending_topics") as rank, \
                 patch.object(pipeline, "search_web", return_value=[{"url": "x"}]), \
                 patch.object(pipeline, "analyze_research", return_value={}), \
                 patch.object(pipeline, "generate_content", return_value=[{
                     "title": "Selected",
                     "angle": "angle",
                     "hook": "hook",
                     "narration": "narration",
                     "description": "description",
                     "cta": "cta",
                 }]), \
                 patch.object(pipeline, "create_content_video", return_value=final_video), \
                 patch("app.topic_history.record_topics"):
                result = pipeline.run_pipeline(
                    content_count=1,
                    selected_topics=selected,
                )

        collect.assert_not_called()
        rank.assert_not_called()
        self.assertEqual(result["selected_topics"], selected)
        self.assertEqual(len(result["completed_videos"]), 1)

    def test_failed_topic_does_not_kill_batch(self):
        first = trends.TrendItem("news", "First")
        second = trends.TrendItem("news", "Second")
        selected = [
            self.make_topic(first, "First"),
            self.make_topic(second, "Second"),
        ]

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)

            def render(content, topic, research, target, index):
                if topic == "First":
                    raise RuntimeError("render failed")
                output = target / "final_short.mp4"
                output.touch()
                return output

            with patch.object(pipeline, "create_run", return_value=run_dir), \
                 patch.object(pipeline, "search_web", return_value=[{"url": "x"}]), \
                 patch.object(pipeline, "analyze_research", return_value={}), \
                 patch.object(pipeline, "generate_content", return_value=[{
                     "title": "Selected",
                     "angle": "angle",
                     "hook": "hook",
                     "narration": "narration",
                     "description": "description",
                     "cta": "cta",
                 }]), \
                 patch.object(pipeline, "create_content_video", side_effect=render), \
                 patch("app.topic_history.record_topics"):
                result = pipeline.run_pipeline(
                    content_count=2,
                    selected_topics=selected,
                )

        self.assertEqual(len(result["completed_videos"]), 1)
        self.assertEqual(result["video_records"][0]["status"], "failed")
        self.assertEqual(result["video_records"][1]["status"], "completed")

    def test_telegram_displays_the_topics_passed_to_pipeline(self):
        item = trends.TrendItem("news", "Selected source")
        selected = [
            self.make_topic(item, "First selected", "science"),
            self.make_topic(item, "Second selected", "sports"),
        ]

        class Message:
            def __init__(self):
                self.messages = []

            async def reply_text(self, text):
                self.messages.append(text)

        class Update:
            def __init__(self):
                self.message = Message()

        class Context:
            args = []

        run_info = {
            "completed_videos": [],
            "selected_topics": selected,
            "video_records": [],
        }

        async def run_test():
            with patch.object(main, "collect_trends", return_value=[item]), \
                 patch.object(main, "rank_trending_topics", return_value=selected) as rank, \
                 patch.object(main, "run_pipeline", return_value=run_info) as run_pipeline:
                update = Update()
                await main.run(update, Context())
                return update, rank, run_pipeline

        update, rank, run_pipeline = asyncio.run(run_test())
        rank.assert_called_once_with([item], 8)
        run_pipeline.assert_called_once_with(
            niche="",
            content_count=8,
            selected_topics=selected,
        )
        selection_message = next(
            message
            for message in update.message.messages
            if "Selected 2 stories" in message
        )
        self.assertIn("First selected", selection_message)
        self.assertIn("Second selected", selection_message)


if __name__ == "__main__":
    unittest.main()
