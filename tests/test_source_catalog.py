"""The configured source catalog covers every user-selectable category."""

import unittest

from finnews.sources import REGISTRY, build_sources
from finnews.sources.base import make_session


EXPECTED_CATEGORY_SOURCES = {
    "google_ai",
    "google_technology",
    "google_consumer_electronics",
    "google_business",
    "google_markets",
    "google_politics",
    "google_sports",
    "google_entertainment",
    "google_social_trends",
    "github_blog",
    "github_trending",
    "github_search",
    "hacker_news",
    "lobsters",
    "weibo_hot",
    "oschina_rss",
    "jiqizhixin_rss",
    "36kr_rss",
    "venturebeat_rss",
    "arstechnica_rss",
    "phoronix_rss",
    "theverge_rss",
}


class SourceCatalogTests(unittest.TestCase):
    def test_every_category_source_is_registered(self):
        self.assertTrue(EXPECTED_CATEGORY_SOURCES.issubset(REGISTRY))

    def test_enabled_category_sources_are_built(self):
        config = {
            "request_interval": 0,
            "sources": {name: {"enabled": True} for name in EXPECTED_CATEGORY_SOURCES},
        }
        session = make_session()
        try:
            self.assertEqual({source.name for source in build_sources(config, session)}, EXPECTED_CATEGORY_SOURCES)
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
