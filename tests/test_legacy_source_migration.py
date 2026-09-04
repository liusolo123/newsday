"""Regression coverage for sources migrated from the legacy daily digest."""

import unittest

from app.services.news import classify_news
from finnews.sources.community import GitHubSearchSource, GitHubTrendingSource, HackerNewsSource, LobstersSource
from finnews.sources.technology import JiqizhixinRssSource
from finnews.sources.weibo import WeiboHotSource


class _Response:
    def __init__(self, *, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class LegacySourceMigrationTests(unittest.TestCase):
    def test_github_sources_keep_direct_repository_links(self):
        trending = GitHubTrendingSource(
            _Session([_Response(text='<article class="Box-row"><h2><a href="/openai/example">openai / example</a></h2><p>Tool</p></article>')]),
            interval=0,
        ).fetch()
        self.assertEqual(trending[0].url, "https://github.com/openai/example")
        session = _Session([_Response(payload={"items": [{"full_name": "openai/new", "description": "A project", "html_url": "https://github.com/openai/new"}]})])
        search = GitHubSearchSource(session, interval=0).fetch()
        self.assertEqual(search[0].source, "github_search")
        self.assertIn("created:>", session.calls[0][1]["params"]["q"])

    def test_community_and_weibo_sources_normalize_public_payloads(self):
        hacker_news = HackerNewsSource(
            _Session([_Response(payload=[1]), _Response(payload={"type": "story", "title": "HN item", "url": "https://example.com", "time": 1})]),
            interval=0,
        ).fetch()
        lobsters = LobstersSource(
            _Session([_Response(payload=[{"title": "Lobsters item", "url": "https://example.org"}])]), interval=0
        ).fetch()
        weibo = WeiboHotSource(
            _Session([_Response(payload={"data": {"realtime": [{"word": "测试热搜", "num": 123}]}})]), interval=0
        ).fetch()
        self.assertEqual((hacker_news[0].source, lobsters[0].source, weibo[0].source), ("hacker_news", "lobsters", "weibo_hot"))
        self.assertEqual(classify_news(weibo[0].title, weibo[0].summary, weibo[0].source), "social_trends")

    def test_migrated_technology_rss_uses_standard_rss_adapter(self):
        session = _Session([_Response(text="")])
        source = JiqizhixinRssSource(session, interval=0)
        self.assertEqual(source.name, "jiqizhixin_rss")
        self.assertEqual(source.url, "https://www.jiqizhixin.com/rss")


if __name__ == "__main__":
    unittest.main()
