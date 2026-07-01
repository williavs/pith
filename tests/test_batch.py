"""Offline tests for the list/batch feature — no network."""
import json

from pith.cli import (read_targets, run_batch, render, _section_links, score_relevance, gate,
                      _company_social, _company_emails, _registrable, render_enrich)
from pith.core import Result, ExtractResult


def test_company_emails_keeps_on_domain_drops_demo():
    # kevin@encom.com is Linear's demo data; hello@linear.app is the real contact
    got = _company_emails(["hello@linear.app", "kevin@encom.com", "support@other.io"], "https://linear.app")
    assert got == ["hello@linear.app"]


def test_registrable_domain():
    assert _registrable("https://www.linear.app/careers") == "linear.app"
    assert _registrable("https://mail.google.com") == "google.com"


def test_company_social_prefers_name_match_skips_personal():
    socials = ["https://github.com/1rgs", "https://github.com/vercel", "https://linkedin.com/company/vercel"]
    # 'Vercel' -> github.com/vercel (name match), NOT the personal 1rgs
    assert _company_social(socials, "Vercel", "github.com") == "https://github.com/vercel"
    assert _company_social(socials, "Vercel", "linkedin.com/company") == "https://linkedin.com/company/vercel"
    # 'Ramp' has only a personal github -> return None rather than the false positive
    assert _company_social(["https://github.com/1rgs"], "Ramp", "github.com") is None


def test_render_enrich_csv():
    rows = [{"company": "Acme", "website": "https://acme.com", "pages": 3, "linkedin": "https://linkedin.com/company/acme",
             "github": None, "twitter": None, "careers": True, "emails": ["hi@acme.com"]}]
    csv_out = render_enrich(rows, "csv")
    assert "company,website,pages" in csv_out.splitlines()[0]
    assert "Acme,https://acme.com,3" in csv_out and "hi@acme.com" in csv_out


def test_score_relevance_counts_query_tokens():
    q = "buyer signals Matt MacInnis Rippling"
    # signal page mentions person+company; competitor mentions neither
    assert score_relevance(q, "https://x.com/Rippling", "Matt MacInnis CPO Rippling") > \
           score_relevance(q, "https://crunchbase.com/organization/deel", "Deel global payroll")
    # short tokens ignored (the/of), case-insensitive
    assert score_relevance("the OF Rippling", "https://rippling.com", "") == 1


def test_gate_keeps_top_budget_by_relevance():
    q = "Matt MacInnis Rippling"
    targets = [("a", "https://other.com/x"), ("b", "https://x.com/Rippling"),
               ("c", "https://crunchbase.com/organization/rippling")]
    snippets = {"https://x.com/Rippling": "Matt MacInnis Rippling",
                "https://crunchbase.com/organization/rippling": "Rippling profile"}
    kept = gate(targets, q, budget=2, snippets=snippets)
    assert [u for _, u in kept] == ["https://x.com/Rippling", "https://crunchbase.com/organization/rippling"]
    assert len(gate(targets, q)) == 3  # no budget = rank all


def test_section_links_filters_dedups_bounds():
    seed = "https://acme.com/"
    html = '''
      <a href="/about-us">About</a>
      <a href="/team">Team</a> <a href="/team">Team dup</a>
      <a href="https://twitter.com/acme">off-domain about</a>
      <a href="/pricing">no signal section</a>
      <a href="/contact#form">Contact</a>
      <a href="/careers">Careers</a>
    '''
    got = _section_links(seed, html, ("about", "team", "contact", "careers"), limit=25)
    urls = [u for _, u in got]
    assert urls[0] == seed                                   # seed first
    assert "https://acme.com/about-us" in urls
    assert "https://acme.com/team" in urls
    assert urls.count("https://acme.com/team") == 1          # deduped
    assert "https://acme.com/contact" in urls                # #fragment stripped
    assert "https://acme.com/pricing" not in urls            # not a target section
    assert all("twitter.com" not in u for u in urls)         # off-domain dropped


def test_section_links_respects_limit():
    seed = "https://x.com/"
    html = "".join(f'<a href="/about/{i}">a</a>' for i in range(50))
    got = _section_links(seed, html, ("about",), limit=5)
    assert len(got) == 5  # seed + 4 matches


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
    return run_batch(_FakeExtractor(), targets, full=False, render_js="auto", workers=1)


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
    seq = run_batch(_FakeExtractor(), targets, full=False, render_js="auto", workers=1)
    par = run_batch(_FakeExtractor(), targets, full=False, render_js="auto", workers=3)
    assert [l for l, u, r in seq] == [l for l, u, r in par]  # order preserved
