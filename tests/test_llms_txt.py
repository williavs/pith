"""write_llms_txt: URL->local-path mirroring, the llms.txt index, and same-path disambiguation."""
import os

from pith.core import Result
from pith.cli import write_llms_txt, _llms_path


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


def test_path_collision(tmp_path):
    rows = [
        ("", "https://d.co/p", Result(url="https://d.co/p", title="A", markdown="one")),
        ("", "https://d.co/p/", Result(url="https://d.co/p/", title="B", markdown="two")),
    ]
    write_llms_txt(rows, str(tmp_path))
    # /p -> p.md ; /p/ -> p/index.md — distinct, no clobber
    assert (tmp_path / "p.md").read_text() == "# A\n\none"
    assert (tmp_path / "p/index.md").read_text() == "# B\n\ntwo"
