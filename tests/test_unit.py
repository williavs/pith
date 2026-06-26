"""Offline unit tests — no network. Fast, run on every commit."""
from pith.core import _needs_browser, _split_frontmatter, _looks_thin, _BROWSER_ONLY


def test_browser_routing_matches_walled_sites():
    for host in ["https://reddit.com/r/x", "https://www.linkedin.com/in/x",
                 "https://old.reddit.com/r/x", "https://www.indeed.com/cmp/x/jobs",
                 "https://m.facebook.com/x", "https://www.trustpilot.com/review/x.com"]:
        assert _needs_browser(host), host


def test_browser_routing_skips_normal_sites():
    for host in ["https://example.com", "https://www.un.org/x", "https://news.ycombinator.com",
                 "https://notreddit.com.evil.com"]:  # suffix-attack must NOT match reddit.com
        assert not _needs_browser(host), host


def test_every_browser_only_domain_routes():
    for d in _BROWSER_ONLY:
        assert _needs_browser(f"https://www.{d}/anything")


def test_split_frontmatter_pulls_metadata():
    md = "---\ntitle: Hello World\ndate: 2021-02-01\n---\n\nBody text here."
    meta, body = _split_frontmatter(md)
    assert meta["title"] == "Hello World"
    assert meta["date"] == "2021-02-01"
    assert body == "Body text here."


def test_split_frontmatter_passthrough_when_absent():
    md = "Just a body, no frontmatter."
    meta, body = _split_frontmatter(md)
    assert meta == {}
    assert body == md


def test_looks_thin():
    assert _looks_thin("")
    assert _looks_thin(None)
    assert _looks_thin("short")
    assert not _looks_thin("x" * 500)


def test_sitemap_parse_filter_dedup_limit(monkeypatch):
    from pith import cli
    sitemap = (b'<?xml version="1.0"?><urlset>'
               b'<url><loc>https://d.dev/router/intro/</loc></url>'
               b'<url><loc>https://d.dev/router/layout/</loc></url>'
               b'<url><loc>https://d.dev/build/eas/</loc></url>'
               b'<url><loc>https://d.dev/router/intro/</loc></url>'  # dup
               b'</urlset>')

    class FakeResp:
        def read(self): return sitemap

    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **k: FakeResp())
    # all, deduped, order preserved, labels None
    t = cli.read_sitemap("https://d.dev/sitemap.xml")
    assert [u for _, u in t] == ["https://d.dev/router/intro/",
                                 "https://d.dev/router/layout/",
                                 "https://d.dev/build/eas/"]
    assert all(label is None for label, _ in t)
    # --match filter
    t = cli.read_sitemap("https://d.dev/sitemap.xml", match="/router/")
    assert len(t) == 2 and all("/router/" in u for _, u in t)
    # --limit cap
    assert len(cli.read_sitemap("https://d.dev/sitemap.xml", limit=1)) == 1
