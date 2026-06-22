"""Live source tests — hit the real walled sites and confirm we still get public content.

These are the canary: if a site changes its defenses and our method stops working, the
matching test fails loud. They need network + the [js] browser extra.

Run only these:   pytest -m live
Skip them (CI unit-only):  pytest -m "not live"
One source:        pytest -m live -k reddit
"""
import pytest

from pith import Extractor

# (id, url, min_bytes, must_contain_any) — must_contain proves it's real content, not a wall page
CONTENT_SOURCES = [
    ("reddit_sub",     "https://www.reddit.com/r/Python/",                     1500, ["python", "comments"]),
    ("linkedin_co",    "https://www.linkedin.com/company/nasa/",               1500, ["nasa", "space"]),
    ("linkedin_person","https://www.linkedin.com/in/williamhgates/",           1500, ["gates", "foundation"]),
    ("instagram",      "https://www.instagram.com/nasa/",                      1500, ["nasa"]),
    ("x",              "https://x.com/NASA",                                    800, ["nasa"]),
    ("medium",         "https://medium.com/@dhh",                              1000, ["dhh", "signal"]),
    ("crunchbase",     "https://www.crunchbase.com/organization/stripe",       1000, ["stripe"]),
    ("indeed",         "https://www.indeed.com/cmp/Stripe/jobs",               1500, ["stripe", "job"]),
    ("producthunt",    "https://www.producthunt.com/products/notion",          1500, ["notion"]),
    ("trustpilot",     "https://www.trustpilot.com/review/stripe.com",         3000, ["stripe", "review"]),
]

# partials: we only guarantee *some* public content, not full body or any specific keyword
# (e.g. a Threads handle page shows posts that needn't mention the handle).
PARTIAL_SOURCES = [
    ("facebook", "https://www.facebook.com/NASA/",        300),
    ("threads",  "https://www.threads.net/@nasa",         300),
    ("glassdoor","https://www.glassdoor.com/Overview/Working-at-Stripe-EI_IE671932.11,17.htm", 300),
]

# phrases that mean we got a login/anti-bot wall instead of content
WALL_PHRASES = ("you must log in to continue", "sign in to continue", "are you a robot",
                "verify you are human", "press & hold", "access denied",
                "enable javascript and cookies")


@pytest.fixture(scope="module")
def ex():
    return Extractor()


@pytest.mark.live
@pytest.mark.parametrize("name,url,min_bytes,needles", CONTENT_SOURCES, ids=[s[0] for s in CONTENT_SOURCES])
def test_source_yields_content(ex, name, url, min_bytes, needles):
    out = ex.extract(urls=[url])
    assert not out.errors, f"{name}: {out.errors}"
    md = out.results[0].excerpts[0].lower()
    assert len(md) >= min_bytes, f"{name}: only {len(md)}B (wall?)"
    assert any(n in md for n in needles), f"{name}: none of {needles} found"


@pytest.mark.live
@pytest.mark.parametrize("name,url,min_bytes", PARTIAL_SOURCES, ids=[s[0] for s in PARTIAL_SOURCES])
def test_partial_source_yields_some_content(ex, name, url, min_bytes):
    """Partials must return *some* public content and must NOT be a pure login wall."""
    out = ex.extract(urls=[url])
    assert not out.errors, f"{name}: {out.errors}"
    md = out.results[0].excerpts[0].lower()
    assert len(md) >= min_bytes, f"{name}: only {len(md)}B"
    assert not any(p in md for p in WALL_PHRASES), f"{name}: looks like a login wall"
