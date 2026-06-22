"""Offline tests for the list/batch feature — no network."""
import json

from pith.cli import read_targets, run_batch, render
from pith.core import Result, ExtractResult


def test_read_targets_txt(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text("https://a.com\n\n# a comment\nhttps://b.com\n")
    assert read_targets(str(p)) == [(None, "https://a.com"), (None, "https://b.com")]


def test_read_targets_csv_label_first(tmp_path):
    p = tmp_path / "c.csv"
    p.write_text("Stripe,https://stripe.com\nLinear,https://linear.app\n")
    assert read_targets(str(p)) == [("Stripe", "https://stripe.com"), ("Linear", "https://linear.app")]


def test_read_targets_url_first_and_junk(tmp_path):
    p = tmp_path / "c.csv"
    # url-first, plus a junk line with no URL (must be skipped, not crash)
    p.write_text("https://x.com,X Corp\nnot-a-url,still-not\nMedium,https://medium.com\n")
    assert read_targets(str(p)) == [("X Corp", "https://x.com"), ("Medium", "https://medium.com")]


class _FakeExtractor:
    """Returns a canned Result per URL, or an error for any URL containing 'bad'."""
    def extract(self, urls, **kw):
        url = urls[0]
        if "bad" in url:
            return ExtractResult(errors=[{"url": url, "error": "no extractable content"}])
        return ExtractResult(results=[Result(url=url, title="T", excerpts=["body text here"])])


def _rows():
    targets = [("Good", "https://good.com"), ("Bad", "https://bad.com")]
    return run_batch(_FakeExtractor(), targets, objective=None, full=False, render_js="auto", workers=1)


def test_run_batch_maps_results_and_errors():
    rows = _rows()
    assert [l for l, u, r in rows] == ["Good", "Bad"]
    assert isinstance(rows[0][2], Result)
    assert rows[1][2]["error"] == "no extractable content"


def test_render_json():
    out = json.loads(render(_rows(), "json"))
    assert out["results"][0]["label"] == "Good"
    assert out["results"][0]["title"] == "T"
    assert out["errors"][0]["label"] == "Bad"


def test_render_table_has_summary():
    out = render(_rows(), "table")
    assert "ok" in out and "ERROR" in out
    assert "1 ok, 1 errors" in out


def test_render_markdown_has_labels():
    out = render(_rows(), "md")
    assert "## Good" in out and "# T" in out and "body text here" in out
    assert "1 ok, 1 errors" in out


def test_run_batch_parallel_matches_sequential():
    targets = [("A", "https://a.com"), ("B", "https://b.com"), ("C", "https://c.com")]
    seq = run_batch(_FakeExtractor(), targets, objective=None, full=False, render_js="auto", workers=1)
    par = run_batch(_FakeExtractor(), targets, objective=None, full=False, render_js="auto", workers=3)
    assert [l for l, u, r in seq] == [l for l, u, r in par]  # order preserved
