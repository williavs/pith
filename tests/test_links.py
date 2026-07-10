"""page_links: harvest absolute, deduped http(s) links from HTML.
read_links: --match filter + scheme/trailing-slash dedup of the target list."""
from pith.extract import page_links
from pith.cli import read_links


def test_page_links_absolute_and_deduped():
    html = '''
      <a href="/a/post-1">rel</a>
      <a href="https://x.com/a/post-2#frag">abs + fragment</a>
      <a href="https://x.com/a/post-1">dup of rel (same absolute)</a>
      <a href="mailto:z@x.com">not http</a>
      <a href="ftp://x.com/f">not http</a>
    '''
    links = page_links(html, "https://x.com/hub")
    assert links == ["https://x.com/a/post-1", "https://x.com/a/post-2"]  # abs, deduped, fragment-stripped, http-only


class _Out:
    def __init__(self, links):
        self.results = [type("R", (), {"links": links})()]


def test_read_links_match_and_scheme_dedup(monkeypatch):
    ex = type("Ex", (), {"extract": lambda self, urls, render_js: _Out([
        "https://h.com/2015/01/logic-noise-a/",
        "http://h.com/2015/01/logic-noise-a",        # same resource: http + no trailing slash
        "https://www.h.com/2015/01/logic-noise-a/",  # same resource: www
        "https://h.com/2015/02/other-thing/",        # dropped by --match
    ])})()
    targets = read_links(ex, "https://h.com/hub", match="logic-noise")
    assert targets == [(None, "https://h.com/2015/01/logic-noise-a/")]   # one unique logic-noise article


def test_read_links_limit(monkeypatch):
    ex = type("Ex", (), {"extract": lambda self, urls, render_js: _Out(
        [f"https://h.com/p{i}" for i in range(10)])})()
    assert len(read_links(ex, "https://h.com/hub", limit=3)) == 3
