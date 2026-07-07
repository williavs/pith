"""Rank companies for a custom-software sell — from the firmographic columns an Apollo/ZoomInfo
export ALREADY carries (Technologies, # Employees, Revenue, Funding, Industry). No network, no
enrichment, instant on 100k rows — because the data is already there. Use this when the list has
firmographics; use enrich.py only when it doesn't (email-only lists).

Scoring is transparent + tuned to the wedge (Jim's play): a company running glue/no-code tools
(Zapier/Airtable/Lindy/spreadsheets) at a fundable size is overpaying for duct-tape → a prime
custom-build target. Output = ranked companies + the exact tool segment to lead the pitch with.

Run: uv run --with pandas python examples/list-cleaner/rank_from_columns.py verified_40k.trimmed.csv -o ranked.csv
"""
import argparse
import os
import re
import sys

import pandas as pd

# "duct-tape ops" tools — a company leaning on these is a wedge target ("replace your <tool>
# credit-burn with a flat-rate custom build"). The segment you match becomes the pitch angle.
DUCT_TAPE = {
    "zapier": "Zapier", "airtable": "Airtable", "make.com": "Make", "integromat": "Make",
    "lindy": "Lindy", "monday.com": "Monday", "monday ": "Monday", "smartsheet": "Smartsheet",
    "retool": "Retool", "bubble": "Bubble", "glide": "Glide", "softr": "Softr",
    "typeform": "Typeform", "jotform": "Jotform", "google sheets": "Google Sheets",
    "spreadsheet": "Spreadsheets", "microsoft excel": "Excel", "zoho creator": "Zoho",
    "quickbase": "Quickbase", "knack": "Knack", "stacker": "Stacker",
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def duct_tape_stack(tech):
    """Which glue tools this company runs -> the wedge segment string."""
    t = str(tech).lower()
    hits = sorted({label for key, label in DUCT_TAPE.items() if key in t})
    return ", ".join(hits)


def score(row):
    """Transparent sell-fit for a custom-software build. No black box — every term is legible."""
    s = 0
    wedge = row["_wedge"]
    s += min(len(wedge.split(", ")) if wedge else 0, 4) * 6      # duct-tape tools = the wedge, weighted hardest
    emp = _num(row.get("# Employees"))
    if 20 <= emp <= 500:  s += 8                                 # sweet spot: big enough to buy, small enough to move
    elif 10 <= emp < 20 or 500 < emp <= 2000: s += 4
    if _num(row.get("Total Funding")) or _num(row.get("Latest Funding Amount")): s += 6   # has budget
    rev = _num(row.get("Annual Revenue"))
    if 1e6 <= rev <= 1e8: s += 4                                 # can afford, not enterprise-procurement
    s += min(int(row.get("_contacts", 1)), 6)                   # more contacts = more ways in
    return s


def run(path, out, company_col, tech_col, email_col, top):
    df = pd.read_csv(os.path.expanduser(path), low_memory=False)
    df[company_col] = df[company_col].fillna("").astype(str)
    df["_wedge"] = df.get(tech_col, "").apply(duct_tape_stack)

    # dedupe to companies: aggregate contacts, keep the firmographics + a representative email
    agg = {c: "first" for c in df.columns if c != company_col}
    agg[email_col] = "first"
    grp = df[df[company_col] != ""].groupby(company_col, sort=False)
    comp = grp.agg(agg)
    comp["_contacts"] = grp.size()
    comp["score"] = comp.apply(score, axis=1)

    cols = [company_col, "_contacts", "score", "_wedge", "# Employees", "Annual Revenue",
            "Total Funding", "Industry", "Website",
            # the representative contact to reach — carried through so the shortlist is actionable
            "First Name", "Last Name", "Title", email_col, "Person Linkedin Url", "Work Direct Phone"]
    r = comp.reset_index()
    ranked = r.sort_values("score", ascending=False)[[c for c in cols if c in r.columns]]
    ranked = ranked.rename(columns={"_wedge": "duct_tape_stack", "_contacts": "contacts"})
    if top:
        ranked = ranked.head(top)
    ranked.to_csv(os.path.expanduser(out), index=False)

    print(f"{len(df):,} contacts -> {comp.shape[0]:,} companies -> top {len(ranked):,} written to {out}\n")
    # segment summary: which wedge tools show up, and how many top companies run each
    seg = {}
    for w in ranked["duct_tape_stack"]:
        for tool in (w.split(", ") if w else []):
            seg[tool] = seg.get(tool, 0) + 1
    print("wedge segments in the shortlist (lead the pitch with these):")
    for tool, n in sorted(seg.items(), key=lambda x: -x[1]):
        print(f"  {tool:16} {n} companies")
    print("\ntop 15:")
    show = ["score", company_col, "contacts", "duct_tape_stack", "# Employees", "Industry"]
    print(ranked[[c for c in show if c in ranked.columns]].head(15).to_string(index=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Rank companies from an export's existing firmographic columns.")
    ap.add_argument("file")
    ap.add_argument("-o", "--out", default="ranked.csv")
    ap.add_argument("--company-col", default="Company")
    ap.add_argument("--tech-col", default="Technologies")
    ap.add_argument("--email-col", default="Email")
    ap.add_argument("--top", type=int, default=500, help="write top N (0 = all)")
    a = ap.parse_args()
    run(a.file, a.out, a.company_col, a.tech_col, a.email_col, a.top or None)
