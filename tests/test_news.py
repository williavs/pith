"""Keyless news search — signal tagging + RSS parse are deterministic (offline); the live
Google/Bing fetch is marked live."""
import pytest

from pith.news import _signal, _rss, news_search


def test_signal_tagging():
    assert _signal("Ramp bags $750M in Series F round") == "funding"
    assert _signal("Ramp elevates CTO to co-CEO") == "leadership"
    assert _signal("Acme discloses data breach affecting 2M users") == "security"
    assert _signal("Stripe acquires Bridge for $1.1B") == "m&a"
    assert _signal("GitLab launches 19.0 with agentic AI") == "product"   # product before ai
    assert _signal("Company opens new office in Berlin") == "expansion"
    assert _signal("Quarterly earnings meet estimates") == "news"          # no intent keyword


def test_rss_parse_rss_and_atom():
    rss = ('<rss><channel>'
           '<item><title>Ramp raises $750M</title><link>https://x.com/a</link>'
           '<pubDate>Wed, 01 Jul 2026 12:00:00 GMT</pubDate><source url="https://tc.com">TechCrunch</source></item>'
           '<item><title>Empty date item</title><link>https://x.com/b</link></item>'
           '</channel></rss>')
    items = _rss(rss, "bing", True)
    assert len(items) == 2
    assert items[0]["title"] == "Ramp raises $750M" and items[0]["source"] == "TechCrunch"
    assert items[0]["date"].year == 2026 and items[0]["extractable"] is True
    assert items[1]["date"] is None                       # missing pubDate -> None, not a crash
    # Atom feed (company blogs) parses too, via the <link href=...> + <updated> ISO date
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom">'
            '<entry><title>New product launch</title><link href="https://co.com/p"/>'
            '<updated>2026-06-30T00:00:00Z</updated></entry></feed>')
    a = _rss(atom, "blog", True)
    assert a[0]["title"] == "New product launch" and a[0]["url"] == "https://co.com/p"
    assert a[0]["date"].year == 2026
    assert _rss("not xml", "x", True) == []               # bad feed -> [] not exception


def test_empty_company():
    assert news_search("") == []


@pytest.mark.live
def test_news_search_live_multi_source():
    items = news_search("Stripe", domain="stripe.com", window_days=60)
    assert len(items) > 10
    assert all("title" in i and "signal" in i and "provider" in i for i in items)
    providers = {i["provider"] for i in items}
    assert len(providers) >= 2                             # NOT relying on one source (hn/bing/blog/google)
    assert sum(i["extractable"] for i in items) >= 5       # real extractable URLs, not just Google tokens
