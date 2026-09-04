"""Direct public technology RSS feeds migrated from the legacy daily digest."""

from __future__ import annotations

from .rss import RssSource


class OscnRssSource(RssSource):
    name = "oschina_rss"
    weight = 3
    url = "https://www.oschina.net/news/rss"


class JiqizhixinRssSource(RssSource):
    name = "jiqizhixin_rss"
    weight = 4
    url = "https://www.jiqizhixin.com/rss"


class Kr36RssSource(RssSource):
    name = "36kr_rss"
    weight = 3
    url = "https://36kr.com/feed"


class VentureBeatRssSource(RssSource):
    name = "venturebeat_rss"
    weight = 4
    url = "https://venturebeat.com/feed/"


class ArsTechnicaRssSource(RssSource):
    name = "arstechnica_rss"
    weight = 4
    url = "https://feeds.arstechnica.com/arstechnica/index"


class PhoronixRssSource(RssSource):
    name = "phoronix_rss"
    weight = 3
    url = "https://www.phoronix.com/rss.php"


class TheVergeRssSource(RssSource):
    name = "theverge_rss"
    weight = 4
    url = "https://www.theverge.com/rss/index.xml"
