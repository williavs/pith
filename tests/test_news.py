"""Keyless news search — signal tagging + RSS parse are deterministic (offline); the live
Google/Bing fetch is marked live."""
import pytest

from pith.news import _signal, _rss_items, news_search


def test_signal_tagging():
    assert _signal("Ramp bags $750M in Series F round") == "funding"
    assert _signal("Ramp elevates CTO to co-CEO") == "leadership"
    assert _signal("Acme discloses data breach affecting 2M users") == "security"
    assert _signal("Stripe acquires Bridge for $1.1B") == "m&a"
    assert _signal("GitLab launches 19.0 with agentic AI") == "product"   # product before ai
    assert _signal("Company opens new office in Berlin") == "expansion"
    assert _signal("Quarterly earnings meet estimates") == "news"          # no intent keyword


def test_rss_parse():
    xml = ('<rss><channel>'
           '<item><title>Ramp raises $750M</title><link>https://x.com/a</link>'
           '<pubDate>Wed, 01 Jul 2026 12:00:00 GMT</pubDate><source url="https://tc.com">TechCrunch</source></item>'
           '<item><title>Empty date item</title><link>https://x.com/b</link></item>'
           '</channel></rss>')
    items = _rss_items(xml, False)
    assert len(items) == 2
    assert items[0]["title"] == "Ramp raises $750M" and items[0]["source"] == "TechCrunch"
    assert items[0]["date"].year == 2026
    assert items[1]["date"] is None                       # missing pubDate -> None, not a crash
    assert _rss_items("not xml", False) == []             # bad feed -> [] not exception


def test_empty_company():
    assert news_search("") == []


@pytest.mark.live
def test_news_search_live():
    items = news_search("GitLab", window_days=60)
    assert len(items) > 5
    assert all("title" in i and "signal" in i and "provider" in i for i in items)
    assert any(i["extractable"] for i in items)            # Bing supplies real article URLs
