"""Parallel Extract API compatibility + per-row failure reporting — the real-user (Gab)
asks: keep the drop-in result shape (excerpts/full_content), tell me WHY a URL failed,
and let me set a timeout. All offline (monkeypatch the fetch; no network)."""
from pith import Extractor
from pith.core import Result, _classify_error, UnsafeURL, _tls


def test_result_parallel_compat_properties():
    r = Result(url="https://x", markdown="hello world")
    assert r.excerpts == ["hello world"]      # Parallel shape: markdown as a one-element list
    assert r.full_content == "hello world"
    empty = Result(url="https://x")
    assert empty.excerpts == [] and empty.full_content == ""   # no content -> empty, not [""]


def test_classify_error():
    assert _classify_error(UnsafeURL("bad")) == "unsafe_url"
    assert _classify_error(Exception("The read operation timed out")) == "timeout"
    assert _classify_error(Exception("HTTP Error 404: Not Found")) == "http_404"
    assert _classify_error(Exception("HTTP Error 403: Forbidden")) == "blocked"
    assert _classify_error(Exception("HTTP Error 429: Too Many Requests")) == "blocked"
    assert _classify_error(Exception("Name or service not known")) == "dns"


def test_extract_error_row_has_reason(monkeypatch):
    def boom(self, url, render_js):
        raise Exception("HTTP Error 404: Not Found")
    monkeypatch.setattr(Extractor, "_to_markdown", boom)
    out = Extractor().extract(["https://x/missing"])
    assert out.errors and out.errors[0]["reason"] == "http_404"
    assert out.errors[0]["url"] == "https://x/missing"


def test_unsafe_url_reason_propagates():
    # guard rejection must surface as 'unsafe_url', not get swallowed into a generic error
    out = Extractor().extract(["not-a-url", "ftp://x/y"])
    assert out.errors and {e["reason"] for e in out.errors} == {"unsafe_url"}


def test_empty_page_flagged_not_hidden(monkeypatch):
    def empty(self, url, render_js):
        return {"title": "t", "date": None}, "   ", "<html></html>"
    monkeypatch.setattr(Extractor, "_to_markdown", empty)
    out = Extractor().extract(["https://x/blank"])
    assert out.results and out.results[0].error == "empty"   # returned, but marked
    # a normal short page is NOT flagged — error stays None
    def ok(self, url, render_js):
        return {"title": "t", "date": None}, "This domain is for examples.", "<html>x</html>"
    monkeypatch.setattr(Extractor, "_to_markdown", ok)
    assert Extractor().extract(["https://x/short"]).results[0].error is None


def test_timeout_threads_to_fetch(monkeypatch):
    seen = {}
    def capture(self, url, render_js):
        seen["budget"] = _tls.budget           # the per-call budget visible inside the fetch
        return {"title": None, "date": None}, "body long enough to not be thin " * 10, "<html></html>"
    monkeypatch.setattr(Extractor, "_to_markdown", capture)
    Extractor().extract(["https://x"], timeout=5)
    assert seen["budget"] == 5
    assert _tls.budget is None                 # reset after the call (finally)
