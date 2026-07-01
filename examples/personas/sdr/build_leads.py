"""SDR target-account builder over pith.

Take ~8 real dev-tool companies by domain, enrich each with pith, rank by fit
(reachability + relevance), and write a CSV of leads.

Per company:
    enrich_company(name, website)  -> firmographics: linkedin/github/twitter,
                                       company-matched emails, careers?, tech grade
    website_intel(website)         -> domain age, framework, responsive, dated signals

Fit score (higher = hotter for an SDR selling dev-productivity SaaS):
    reachability: company email(s) found, socials present (linkedin/github/twitter)
    relevance:    has a careers page (hiring devs => budget + pain we solve),
                  github presence (engineering-led org)

Run:  .venv/bin/python examples/personas/sdr/build_leads.py
Output: leads.csv (ranked) + prints highlights to stderr.
"""
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from pith.cli import enrich_company, website_intel

OUT_DIR = Path(__file__).resolve().parent

# Target set: real dev-tool / infra companies (ICP for a dev-productivity SaaS).
TARGETS = [
    ("Stripe", "https://stripe.com"),
    ("Linear", "https://linear.app"),
    ("Vercel", "https://vercel.com"),
    ("Notion", "https://notion.so"),
    ("Retool", "https://retool.com"),
    ("Airtable", "https://airtable.com"),
    ("Figma", "https://figma.com"),
    ("Ramp", "https://ramp.com"),
]


def enrich_one(nc):
    name, website = nc
    row = {"company": name, "website": website}
    try:
        e = enrich_company(name, website)
        row.update(e)
    except Exception as ex:
        row["error"] = str(ex)[:80]
    try:
        i = website_intel(website)
        row["domain_age_years"] = i.get("domain_age_years")
        row["framework"] = i.get("framework")
        row["responsive"] = i.get("responsive")
        row["dated_signals"] = ", ".join(i.get("dated_signals") or [])
    except Exception as ex:
        row["intel_error"] = str(ex)[:80]
    print(f"  {name[:12]:12} grade={row.get('grade','?')} "
          f"emails={len(row.get('emails') or [])} "
          f"li={'y' if row.get('linkedin') else '-'} "
          f"gh={'y' if row.get('github') else '-'} "
          f"careers={'y' if row.get('careers') else '-'}", file=sys.stderr)
    return row


def fit_score(r: dict) -> int:
    emails = r.get("emails") or []
    # reachability: a real company-matched email is the single biggest unblocker
    reach = (2 if emails else 0)
    reach += 1 if r.get("linkedin") else 0
    reach += 1 if r.get("twitter") else 0
    # relevance to a dev-productivity pitch
    rel = 2 if r.get("careers") else 0     # hiring devs => budget + the pain we sell into
    rel += 1 if r.get("github") else 0     # engineering-led org
    return reach + rel


def main():
    print(f"┌─ enriching {len(TARGETS)} accounts", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(enrich_one, TARGETS))
    for r in rows:
        r["fit_score"] = fit_score(r)
        r["email_primary"] = (r.get("emails") or [None])[0]
    rows.sort(key=lambda r: -r["fit_score"])
    print("└─ ranked hottest-first\n", file=sys.stderr)

    cols = ["rank", "company", "website", "fit_score", "grade", "framework",
            "responsive", "domain_age_years", "careers", "github", "linkedin",
            "twitter", "email_primary", "emails"]
    csv_path = OUT_DIR / "leads.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(rows, 1):
            w.writerow({**r, "rank": i, "emails": "; ".join(r.get("emails") or [])})
    print(f"wrote {csv_path}", file=sys.stderr)
    # also dump raw json for the README/plan write-up
    (OUT_DIR / "leads_raw.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
