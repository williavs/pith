"""GTM scenarios — how three different sales teams need the SAME pith output.

A GTM-ops person drops in a list of target companies (their ICP / territory). pith crawls
each company's high-signal sections (about/team/contact/careers) once, abstracting all the
browser/tier/concurrency machinery, and returns robust structured data. Each rep persona
then reads the value THEY need out of that one enrichment — no LLM, all deterministic.

  Persona A — SSPM security rep:  the company's socials (to find the CISO), AI-adoption signal, contact emails
  Persona B — recruiting rep:     is a careers page reachable + a hiring signal (are they scaling?)
  Persona C — dev-tools rep:      GitHub presence + a developer/API signal (are they a technical buyer?)

Run:  ../.venv/bin/python gtm_scenarios.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pith import Extractor
from pith.cli import crawl_site

# a sales rep's ICP list: name, website (the only input GTM ops has to start with)
COMPANIES = [
    ("Linear", "https://linear.app"),
    ("Vercel", "https://vercel.com"),
    ("Ramp", "https://ramp.com"),
    ("Retool", "https://retool.com"),
    ("Notion", "https://www.notion.so"),
]

# deterministic signal keywords per persona (no LLM — honest keyword presence)
AI_SIG = ("artificial intelligence", " ai ", " ai,", " ai.", "machine learning", "llm", "gpt", "copilot", "agent")
HIRING_SIG = ("hiring", "open role", "open position", "join us", "join our", "we're growing", "careers", "apply")
DEV_SIG = ("api", "sdk", "developer", "documentation", "open source", "github", "webhook", "cli")


def _pick_social(socials, needle):
    return next((s for s in socials if needle in s.lower()), None)


def _signal(text, kws):
    low = text.lower()
    return sum(low.count(k) for k in kws)


def enrich(name, website):
    """One pith pass over a company's key sections -> aggregated structured data."""
    targets = crawl_site(website, limit=6)   # homepage + about/team/contact/careers links
    ex = Extractor()
    out = ex.extract([u for _, u in targets], concurrency=4, render_js="auto")
    socials, emails, content, sections = set(), set(), [], []
    for r in out.results:
        socials |= set(r.socials)
        emails |= set(r.emails)
        content.append(r.excerpts[0] if r.excerpts else "")
        sections.append(r.url)
    blob = "\n".join(content)
    return {
        "name": name, "website": website,
        "socials": sorted(socials), "emails": sorted(emails),
        "linkedin": _pick_social(socials, "linkedin.com/company"),
        "github": _pick_social(socials, "github.com"),
        "twitter": _pick_social(socials, "twitter.com") or _pick_social(socials, "x.com"),
        "pages_reached": len(out.results), "errors": len(out.errors),
        "careers_page": any("career" in u or "job" in u for u in sections),
        "ai_signal": _signal(blob, AI_SIG),
        "hiring_signal": _signal(blob, HIRING_SIG),
        "dev_signal": _signal(blob, DEV_SIG),
        "content_chars": len(blob),
    }


def main():
    print(f"GTM enrichment: {len(COMPANIES)} companies, bare website -> structured signal\n")
    rows = [enrich(n, w) for n, w in COMPANIES]

    print("== SHARED pith enrichment (one crawl per company) ==")
    print(f"{'company':10} {'pages':>5} {'chars':>6}  {'linkedin':8} {'github':7} {'careers':7}")
    for r in rows:
        print(f"{r['name']:10} {r['pages_reached']:>5} {r['content_chars']:>6}  "
              f"{'yes' if r['linkedin'] else '-':8} {'yes' if r['github'] else '-':7} {'yes' if r['careers_page'] else '-':7}")

    print("\n== Persona A — SSPM security rep (find the CISO, gauge AI risk) ==")
    print(f"{'company':10} {'AI-signal':>9}  company LinkedIn (-> find security leader) / emails")
    for r in rows:
        print(f"{r['name']:10} {r['ai_signal']:>9}  {r['linkedin'] or '(none)'}  {r['emails'][:2]}")

    print("\n== Persona B — recruiting rep (are they scaling headcount?) ==")
    print(f"{'company':10} {'careers':>7} {'hiring-sig':>10}  read")
    for r in rows:
        verdict = "actively hiring" if r["careers_page"] and r["hiring_signal"] > 3 else \
                  "some signal" if r["hiring_signal"] else "quiet"
        print(f"{r['name']:10} {'yes' if r['careers_page'] else 'no':>7} {r['hiring_signal']:>10}  {verdict}")

    print("\n== Persona C — dev-tools rep (technical buyer?) ==")
    print(f"{'company':10} {'dev-sig':>7}  github")
    for r in rows:
        print(f"{r['name']:10} {r['dev_signal']:>7}  {r['github'] or '(none)'}")

    ok = sum(1 for r in rows if r["pages_reached"])
    print(f"\n{ok}/{len(rows)} companies enriched from just a name+URL. One pipeline, three GTM value-lenses.")


if __name__ == "__main__":
    main()
