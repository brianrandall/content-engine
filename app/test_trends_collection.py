from contextlib import redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from app import trends


class TrendCollectionTests(unittest.TestCase):
    def test_low_value_headline_filter_allows_compelling_sports(self):
        self.assertTrue(trends.is_low_value_headline("Team rankings released"))
        self.assertTrue(trends.is_low_value_headline("Game schedule and odds"))
        self.assertFalse(
            trends.is_low_value_headline(
                "Underdog wins historic championship after stunning upset"
            )
        )

    def test_deduplication_preserves_first_source_and_removes_near_duplicates(self):
        items = [
            trends.TrendItem("google_news", "Actor announces surprise retirement", url="https://one"),
            trends.TrendItem("google_news", "Actor announces a surprise retirement", url="https://two"),
            trends.TrendItem("reddit", "Scientists discover a hidden ocean", url="https://three"),
        ]

        unique = trends._dedupe_trends(items)

        self.assertEqual(len(unique), 2)
        self.assertEqual(unique[0].url, "https://one")
        self.assertEqual(unique[1].source, "reddit")

    def test_targeted_queries_are_collected_when_reddit_fails(self):
        category_titles = {
            "entertainment": "Actor makes unexpected career announcement",
            "weird": "Strange object discovered inside abandoned lighthouse",
            "technology": "New artificial intelligence breakthrough changes industry",
            "science": "Astronomers detect unexplained signal from deep space",
            "business": "Bank collapses after sudden liquidity crisis",
            "politics": "Government announces emergency legislation today",
            "world": "Rescue crews evacuate village after major earthquake",
            "internet": "Social media platform suffers worldwide outage",
            "human-interest": "Volunteers reunite missing child with family",
            "sports": "Underdog wins historic championship in dramatic upset",
        }
        query_items = [
            trends.TrendItem(
                "google_news",
                category_titles[category],
                metadata={"category": category},
            )
            for index, (category, _query) in enumerate(trends.GOOGLE_NEWS_QUERIES)
        ]

        with patch(
            "app.research.search_reddit",
            side_effect=RuntimeError("rate limited"),
        ), patch(
            "app.trends.fetch_hackernews_trends",
            return_value=[],
        ), patch(
            "app.trends.fetch_google_news_query",
            side_effect=[[item] for item in query_items],
        ) as fetch_query, patch(
            "app.news.fetch_google_news_trends",
            return_value=[],
        ), redirect_stdout(StringIO()) as output:
            result = trends.collect_trends(
                reddit_subreddits=["news"],
                hackernews_limit=0,
            )

        self.assertEqual(fetch_query.call_count, len(trends.GOOGLE_NEWS_QUERIES))
        self.assertEqual(len(result), len(trends.GOOGLE_NEWS_QUERIES))
        self.assertIn("Sources:", output.getvalue())
        self.assertIn("Categories:", output.getvalue())

    def test_google_query_parser_filters_and_tags_category(self):
        xml = b"""<rss><channel>
        <item><title>Historic rescue saves a town</title><link>https://one</link><pubDate>Wed, 26 Aug 2026 12:00:00 GMT</pubDate><source>Daily News</source></item>
        <item><title>Top 100 rankings and predictions</title><link>https://two</link></item>
        </channel></rss>"""
        response = type("Response", (), {
            "content": xml,
            "raise_for_status": lambda self: None,
        })()

        with patch("app.trends.requests.get", return_value=response):
            result = trends.fetch_google_news_query(
                "rescue when:1d",
                "human-interest",
                limit=10,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].metadata["category"], "human-interest")
        self.assertEqual(result[0].metadata["publisher"], "Daily News")


if __name__ == "__main__":
    unittest.main()
