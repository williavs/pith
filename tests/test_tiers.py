"""Offline tests for the fetch-tier additions (curl_cffi impersonation + MarkItDown docs).
Network paths are covered by tests/test_live.py; here we test the pure routing logic."""
from pith.core import _is_document, _looks_thin, _DOC_EXTS


def test_is_document_by_extension():
    for url in ["https://x.com/report.pdf", "https://x.com/deck.pptx",
                "https://x.com/sheet.xlsx", "https://x.com/paper.PDF",
                "https://x.com/a.pdf?download=1"]:  # query string must not fool it
        assert _is_document(url), url


def test_is_document_skips_html():
    for url in ["https://x.com/page", "https://reddit.com/r/python",
                "https://x.com/pdf-viewer", "https://x.com/article.html"]:
        assert not _is_document(url), url


def test_doc_exts_are_lowercase_dotted():
    # detection lowercases the path, so the table must be lowercase + dotted to match
    assert all(e.startswith(".") and e.islower() for e in _DOC_EXTS)


def test_looks_thin_boundary():
    # the tier escalation hinges on this: <200 chars triggers the next (costlier) tier
    assert _looks_thin("x" * 199)
    assert not _looks_thin("x" * 200)


def test_thin_escalates_only_when_raw_html_is_big(monkeypatch):
    """Fix: a tiny real page (small raw HTML) must NOT waste ~3s escalating to the browser;
    a JS shell (big raw HTML, thin extract) still must."""
    from pith.core import Extractor
    calls = {"browser": 0}
    ex = Extractor()
    monkeypatch.setattr(Extractor, "_browser_markdown",
                        lambda self, url, attempts=2: (calls.__setitem__("browser", calls["browser"] + 1) or "BROWSERED", "<html>"))

    monkeypatch.setattr(Extractor, "_cheap_markdown", lambda self, url: ("tiny", "x" * 559))   # small page
    meta, body, html = ex._to_markdown("https://example.com", "auto")
    assert body == "tiny" and calls["browser"] == 0                                            # did NOT escalate

    monkeypatch.setattr(Extractor, "_cheap_markdown", lambda self, url: ("", "x" * 50000))     # JS shell
    ex._to_markdown("https://spa.example", "auto")
    assert calls["browser"] == 1                                                               # DID escalate


def test_run_batch_caps_browser_concurrency(monkeypatch):
    """Fix: --workers on a list containing a walled URL is capped so it can't spawn N browsers."""
    from pith import cli
    seen = {}

    class _Ex:
        def extract(self, urls, **kw):
            from pith.core import ExtractResult, Result
            return ExtractResult(results=[Result(url=urls[0], excerpts=["x"])])

    def fake_pool(max_workers):
        seen["workers"] = max_workers
        return __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor(max_workers)
    monkeypatch.setattr(cli, "ThreadPoolExecutor", fake_pool)

    walled = [("a", "https://reddit.com/r/x"), ("b", "https://example.com")]
    cli.run_batch(_Ex(), walled, objective=None, full=False, render_js="auto", workers=16)
    assert seen["workers"] == cli._BROWSER_MAX_CONCURRENCY   # capped from 16

    seen.clear()
    cheap = [("a", "https://example.com"), ("b", "https://foo.com")]
    cli.run_batch(_Ex(), cheap, objective=None, full=False, render_js="auto", workers=16)
    assert seen["workers"] == 16                             # no wall -> uncapped


def test_jsonfmt_emits_event_plus_extra():
    """Trace mode: each record -> one JSON object, message=event, extra= fields ride along."""
    import json, logging
    from pith.cli import _JsonFmt
    rec = logging.LogRecord("pith", logging.INFO, "", 0, "tier", (), None)
    rec.url = "https://x.com"; rec.tier = "browser"; rec.ms = 4655.9
    d = json.loads(_JsonFmt().format(rec))
    assert d == {"event": "tier", "url": "https://x.com", "tier": "browser", "ms": 4655.9}


def test_concurrent_extract_preserves_order_and_errors(monkeypatch):
    """The list-enrichment fast path: concurrency must keep input order and isolate
    failures, same contract as the sequential path."""
    from pith.core import Extractor, Result

    def fake(self, url, render_js):
        if "bad" in url:
            raise RuntimeError("boom")
        return ({"title": "t"}, f"body {url}", "")

    monkeypatch.setattr(Extractor, "_to_markdown", fake)
    ex = Extractor()
    urls = ["https://a.com", "https://bad.com", "https://b.com", "https://c.com"]
    seq = ex.extract(urls, concurrency=1)
    par = ex.extract(urls, concurrency=8)
    # identical results regardless of concurrency
    assert [r.url for r in seq.results] == [r.url for r in par.results] == ["https://a.com", "https://b.com", "https://c.com"]
    assert par.errors[0]["url"] == "https://bad.com"
    assert len(par.results) == 3 and len(par.errors) == 1
