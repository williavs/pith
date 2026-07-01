"""Job-board intelligence. Normalizers are deterministic (offline); ATS discovery is live."""
import pytest

from pith.jobs import _n_greenhouse, _n_lever, _n_ashby, jobs_search


def test_greenhouse_normalizer():
    d = {"jobs": [{"title": "Staff Security Engineer",
                   "location": {"name": "Remote - US"},
                   "departments": [{"name": "Security"}],
                   "absolute_url": "https://x/1", "updated_at": "2026-06-01"}]}
    p = _n_greenhouse(d)[0]
    assert p["title"] == "Staff Security Engineer" and p["location"] == "Remote - US"
    assert p["department"] == "Security" and p["url"] == "https://x/1"


def test_lever_normalizer_bare_list():
    # Lever returns a bare JSON array, not an object
    d = [{"text": "Account Executive", "categories": {"location": "NYC", "team": "Sales"},
          "hostedUrl": "https://jobs.lever.co/co/1"}]
    p = _n_lever(d)[0]
    assert p["title"] == "Account Executive" and p["location"] == "NYC" and p["department"] == "Sales"


def test_ashby_normalizer():
    d = {"jobs": [{"title": "PM", "location": "London", "department": "Product", "jobUrl": "https://a/1"}]}
    assert _n_ashby(d)[0]["department"] == "Product"


@pytest.mark.live
def test_jobs_search_discovers_ats():
    j = jobs_search("Stripe", "stripe.com")
    assert j["ats"] == "greenhouse" and j["count"] > 50
    assert all(p.get("title") for p in j["postings"])
    # honest empty for a custom/walled careers site
    n = jobs_search("Nonexistent Co", "this-domain-does-not-exist-pith.invalid")
    assert n["ats"] is None and n["count"] == 0 and "note" in n
