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


def test_concurrent_extract_preserves_order_and_errors(monkeypatch):
    """The list-enrichment fast path: concurrency must keep input order and isolate
    failures, same contract as the sequential path."""
    from pith.core import Extractor, Result

    def fake(self, url, render_js):
        if "bad" in url:
            raise RuntimeError("boom")
        return ({"title": "t"}, f"body {url}")

    monkeypatch.setattr(Extractor, "_to_markdown", fake)
    ex = Extractor()
    urls = ["https://a.com", "https://bad.com", "https://b.com", "https://c.com"]
    seq = ex.extract(urls, concurrency=1)
    par = ex.extract(urls, concurrency=8)
    # identical results regardless of concurrency
    assert [r.url for r in seq.results] == [r.url for r in par.results] == ["https://a.com", "https://b.com", "https://c.com"]
    assert par.errors[0]["url"] == "https://bad.com"
    assert len(par.results) == 3 and len(par.errors) == 1
