import unittest

from app.editorial import (
    SCORE_WEIGHTS,
    SCORE_FIELDS,
    build_editorial_slate,
    normalize_and_dedupe_trends,
    validate_evaluations,
)
from app.trends import TrendItem


class EditorialSelectionTests(unittest.TestCase):
    def evaluation(self, candidate_id, category="world", score=80):
        evaluation = {
            "candidate_id": candidate_id,
            "category": category,
            "recommended": True,
            "confidence": 90,
            "brief_reason": "Supported by the supplied headline.",
        }
        evaluation.update({field: score for field in SCORE_FIELDS})
        evaluation["opportunity_score"] = score
        return evaluation

    def test_normalization_deduplicates_exact_and_obvious_headlines(self):
        trends = [
            TrendItem("news", "Major company recalls product worldwide"),
            TrendItem("wire", "Major company recalls product worldwide"),
            TrendItem("news", "Scientists discover a new ocean"),
        ]

        candidates = normalize_and_dedupe_trends(trends)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_indices"], [0, 1])
        self.assertEqual(len(candidates[0]["sources"]), 2)

    def test_evaluation_schema_rejects_invalid_values(self):
        candidate = normalize_and_dedupe_trends([
            TrendItem("news", "A story")
        ])
        invalid = self.evaluation(0, "world", 80)
        invalid["curiosity"] = 101

        self.assertEqual(validate_evaluations([invalid], candidate), [])

    def test_valid_evaluation_calculates_weighted_score(self):
        candidate = normalize_and_dedupe_trends([
            TrendItem("news", "A story")
        ])
        evaluation = self.evaluation(0, "world", 80)

        validated = validate_evaluations([evaluation], candidate)

        expected = round(
            sum(80 * weight for weight in SCORE_WEIGHTS.values()),
            2,
        )
        self.assertEqual(validated[0]["opportunity_score"], expected)

    def test_duplicate_evaluations_cannot_fill_multiple_slots(self):
        candidate = normalize_and_dedupe_trends([
            TrendItem("news", "A story")
        ])
        evaluations = validate_evaluations([
            self.evaluation(0, "sports", 90),
            self.evaluation(0, "science", 89),
        ], candidate)

        self.assertEqual(len(evaluations), 1)

    def test_each_normalized_candidate_can_be_evaluated(self):
        candidates = normalize_and_dedupe_trends([
            TrendItem("news", "First story"),
            TrendItem("news", "Second story"),
            TrendItem("news", "First story"),
        ])
        evaluations = validate_evaluations([
            self.evaluation(candidate["candidate_id"])
            for candidate in candidates
        ], candidates)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(evaluations), 2)

    def test_slate_prefers_diversity_when_scores_are_close(self):
        evaluations = [
            self.evaluation(0, "sports", 94),
            self.evaluation(1, "sports", 92),
            self.evaluation(2, "science", 91),
            self.evaluation(3, "business", 90),
        ]
        for evaluation in evaluations:
            evaluation["candidate"] = {
                "candidate_id": evaluation["candidate_id"],
                "title": f"Story {evaluation['candidate_id']}",
                "source_indices": [evaluation["candidate_id"]],
                "sources": [],
            }

        slate, distribution = build_editorial_slate(evaluations, 4)

        self.assertEqual(
            [topic["category"] for topic in slate],
            ["sports", "science", "business", "sports"],
        )
        self.assertEqual(distribution, {"sports": 2, "science": 1, "business": 1})

    def test_exceptional_story_overcomes_repetition_penalty(self):
        evaluations = [
            self.evaluation(0, "sports", 99),
            self.evaluation(1, "sports", 99),
            self.evaluation(2, "sports", 99),
            self.evaluation(3, "science", 70),
        ]
        for evaluation in evaluations:
            evaluation["candidate"] = {
                "candidate_id": evaluation["candidate_id"],
                "title": f"Story {evaluation['candidate_id']}",
                "source_indices": [evaluation["candidate_id"]],
                "sources": [],
            }

        slate, _ = build_editorial_slate(evaluations, 4)

        self.assertEqual(
            [topic["category"] for topic in slate],
            ["sports", "science", "sports", "sports"],
        )

    def test_sports_can_dominate_when_substantially_stronger(self):
        evaluations = [
            *[self.evaluation(index, "sports", 95 - index) for index in range(4)],
            self.evaluation(4, "science", 60),
        ]
        for evaluation in evaluations:
            evaluation["candidate"] = {
                "candidate_id": evaluation["candidate_id"],
                "title": f"Story {evaluation['candidate_id']}",
                "source_indices": [evaluation["candidate_id"]],
                "sources": [],
            }

        slate, _ = build_editorial_slate(evaluations, 4)

        self.assertEqual(
            [topic["category"] for topic in slate],
            ["sports", "science", "sports", "sports"],
        )

    def test_slate_fills_available_slots_without_category_quotas(self):
        evaluations = [self.evaluation(0, "science", 80)]
        evaluations[0]["candidate"] = {
            "candidate_id": 0,
            "title": "Only story",
            "source_indices": [0],
            "sources": [],
        }

        slate, _ = build_editorial_slate(evaluations, 8)

        self.assertEqual(len(slate), 1)

    def test_slate_is_deterministic(self):
        evaluations = []
        for index, category in enumerate(["world", "sports", "science"]):
            evaluation = self.evaluation(index, category, 80)
            evaluation["candidate"] = {
                "candidate_id": index,
                "title": f"Story {index}",
                "source_indices": [index],
                "sources": [],
            }
            evaluations.append(evaluation)

        first, _ = build_editorial_slate(evaluations, 3)
        second, _ = build_editorial_slate(evaluations, 3)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
