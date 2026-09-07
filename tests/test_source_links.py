"""Regression coverage for item-specific source links."""

import unittest

from finnews.sources.eastmoney import Eastmoney724Source
from finnews.sources.sina import SinaLiveSource
from finnews.sources.wallstreetcn import WallstreetCnSource


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class _Session:
    def __init__(self, payload: dict) -> None:
        self.headers: dict[str, str] = {}
        self.payload = payload

    def get(self, *args, **kwargs) -> _Response:
        return _Response(self.payload)


class SourceLinkTests(unittest.TestCase):
    def test_eastmoney_uses_the_api_item_code_for_a_detail_url(self) -> None:
        source = Eastmoney724Source(
            _Session(
                {
                    "code": "1",
                    "data": {
                        "fastNewsList": [
                            {"title": "测试快讯", "summary": "摘要", "code": "202609071234567890"}
                        ]
                    },
                }
            ),
            interval=0,
        )

        self.assertEqual(
            source.fetch()[0].url,
            "https://finance.eastmoney.com/a/202609071234567890.html",
        )

    def test_eastmoney_omits_a_link_when_no_item_code_is_available(self) -> None:
        source = Eastmoney724Source(
            _Session({"code": "1", "data": {"fastNewsList": [{"title": "测试快讯", "code": "bad"}]}}),
            interval=0,
        )

        self.assertEqual(source.fetch()[0].url, "")

    def test_sina_keeps_only_an_explicit_article_url(self) -> None:
        source = SinaLiveSource(
            _Session(
                {
                    "result": {
                        "data": {
                            "feed": {
                                "list": [
                                    {"rich_text": "测试快讯", "docurl": "/article/test.html"},
                                    {"rich_text": "无详情快讯", "docurl": ""},
                                ]
                            }
                        }
                    }
                }
            ),
            interval=0,
        )

        items = source.fetch()
        self.assertEqual(items[0].url, "https://finance.sina.com.cn/article/test.html")
        self.assertEqual(items[1].url, "")

    def test_wallstreet_live_items_use_the_livenews_detail_route(self) -> None:
        source = WallstreetCnSource(
            _Session(
                {
                    "data": {
                        "items": [
                            {"id": 3161004, "title": "测试快讯", "content_text": "摘要", "display_time": 1}
                        ]
                    }
                }
            ),
            interval=0,
        )

        self.assertEqual(source.fetch()[0].url, "https://wallstreetcn.com/livenews/3161004")


if __name__ == "__main__":
    unittest.main()
