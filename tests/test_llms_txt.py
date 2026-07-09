"""write_llms_txt: URL->local-path mirroring, the llms.txt index, and same-path disambiguation.
_fetch_native_md: accept real markdown, reject HTML soft-404s."""
import io
import os

import pith.cli as cli
from pith.core import Result
from pith.cli import write_llms_txt, _llms_path, _fetch_native_md


class _Resp:
    def __init__(self, body, ctype):
        self._b, self.headers = body.encode(), {"Content-Type": ctype}
    def read(self): return self._b
    def __getattr__(self, _): return self.headers.get  # .headers.get(...) shim


def _patch(monkeypatch, body, ctype):
    monkeypatch.setattr(cli.urllib.request, "urlopen", lambda *a, **k: _Resp(body, ctype))


def test_native_md_accepted(monkeypatch):
    _patch(monkeypatch, "# Hooks\n\nhook events here", "text/markdown; charset=utf-8")
    r = _fetch_native_md("https://d.co/docs/hooks")
    assert r is not None and r.title == "Hooks" and r._native is True
    assert r.url == "https://d.co/docs/hooks"          # original url, not the .md candidate


def test_html_soft_404_rejected(monkeypatch):
    _patch(monkeypatch, "<!DOCTYPE html><html><body>Not found</body></html>", "text/html")
    assert _fetch_native_md("https://d.co/docs/hooks") is None


def test_empty_rejected(monkeypatch):
    _patch(monkeypatch, "   ", "text/markdown")
    assert _fetch_native_md("https://d.co/docs/hooks") is None


def test_path_mapping():
    assert _llms_path("https://x.com/docs/en/hooks") == "docs/en/hooks.md"
    assert _llms_path("https://x.com/") == "index.md"
    assert _llms_path("https://x.com/guide/") == "guide/index.md"
    assert _llms_path("https://x.com/a/b.md") == "a/b.md"          # already .md, not doubled


def test_corpus_and_index(tmp_path):
    rows = [
        ("", "https://d.co/docs/en/overview", Result(url="https://d.co/docs/en/overview",
            title="Overview", markdown="the overview", meta={"description": "intro  page"})),
        ("", "https://d.co/docs/en/agent-sdk/hooks", Result(url="https://d.co/docs/en/agent-sdk/hooks",
            title="Hooks", markdown="hook events", meta={})),
        ("", "https://d.co/skip", {"error": "blocked"}),          # errors excluded
    ]
    n = write_llms_txt(rows, str(tmp_path))
    assert n == 2
    assert (tmp_path / "docs/en/overview.md").read_text() == "# Overview\n\nthe overview"
    assert (tmp_path / "docs/en/agent-sdk/hooks.md").exists()     # nested path created
    idx = (tmp_path / "llms.txt").read_text()
    assert "# d.co" in idx
    assert "- [Overview](docs/en/overview.md): intro page" in idx  # desc whitespace collapsed
    assert "- [Hooks](docs/en/agent-sdk/hooks.md)\n" in idx        # no desc -> no trailing colon


def test_native_written_verbatim(tmp_path):
    r = Result(url="https://d.co/hooks", title="Hooks", markdown="# Hooks\n\nfull native body")
    r._native = True                                       # native .md already has its own H1
    write_llms_txt([("", r.url, r)], str(tmp_path))
    assert (tmp_path / "hooks.md").read_text() == "# Hooks\n\nfull native body"   # no double title


def test_path_collision(tmp_path):
    rows = [
        ("", "https://d.co/p", Result(url="https://d.co/p", title="A", markdown="one")),
        ("", "https://d.co/p/", Result(url="https://d.co/p/", title="B", markdown="two")),
    ]
    write_llms_txt(rows, str(tmp_path))
    # /p -> p.md ; /p/ -> p/index.md — distinct, no clobber
    assert (tmp_path / "p.md").read_text() == "# A\n\none"
    assert (tmp_path / "p/index.md").read_text() == "# B\n\ntwo"
