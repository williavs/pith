"""Stage 3 (OSINT): for the TOP shortlist only, find each decision-maker's OTHER public channels
beyond the LinkedIn URL the list already has — so you can reach them where they actually are
(X/GitHub/personal site) when a cold email won't land. Runs on a handful, not the whole list.

- gravatar_profile(email): precise (hash of the email) — linked accounts if they use Gravatar.
- enumerate_profiles(handle): existence across ~480 sites. Handle derived from the LinkedIn slug
  (a real username) — noisier than gravatar (name collisions), so treat as leads to confirm.

Run: uv run --with "pith[osint] @ git+https://github.com/williavs/pith.git@master" --with pandas \
     python examples/list-cleaner/osint_reach.py ranked.csv -o reach.csv --top 25
"""
import argparse
import os
import re
import sys

import pandas as pd
from pith.gravatar import gravatar_profile
from pith.profiles import enumerate_profiles


def _handle(row, email_col):
    """Best username to enumerate: the LinkedIn slug if present, else the email local part."""
    li = str(row.get("Person Linkedin Url", "") or "")
    m = re.search(r"/in/([A-Za-z0-9\-]{3,})", li)
    if m:
        return m.group(1).rstrip("-")
    local = str(row.get(email_col, "")).split("@")[0]
    return re.sub(r"[^a-z0-9]", "", local.lower()) or None


def run(path, out, email_col, top):
    df = pd.read_csv(os.path.expanduser(path), low_memory=False).head(top)
    rows = []
    for i, r in df.iterrows():
        email = str(r.get(email_col, ""))
        chans = []
        # gravatar (precise)
        try:
            g = gravatar_profile(email)
            if g.get("exists"):
                for a in (g.get("accounts") or []):
                    if a.get("url"):
                        chans.append(a["url"])
        except Exception:
            pass
        # enumerate from handle (leads to confirm)
        h = _handle(r, email_col)
        prof = []
        if h:
            try:
                res = enumerate_profiles(h, workers=25, timeout=8)
                prof = [p["url"] for p in (res.get("profiles") if isinstance(res, dict) else res) if p.get("url")]
            except Exception:
                pass
        rows.append({
            "Company": r.get("Company"), "name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
            "email": email, "linkedin": r.get("Person Linkedin Url", ""),
            "gravatar_channels": ", ".join(chans),
            "handle": h, "other_profiles": ", ".join(prof[:8]),
        })
        print(f"  [{i+1}/{len(df)}] {rows[-1]['name'][:24]:24} gravatar:{len(chans)} profiles:{len(prof)}", file=sys.stderr, flush=True)

    outdf = pd.DataFrame(rows)
    outdf.to_csv(os.path.expanduser(out), index=False)
    hit_g = (outdf["gravatar_channels"] != "").sum()
    hit_p = (outdf["other_profiles"] != "").sum()
    print(f"\n{len(outdf)} contacts: gravatar hit {hit_g} ({100*hit_g//len(outdf)}%), "
          f"profile leads {hit_p} ({100*hit_p//len(outdf)}%) -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Find multi-channel reach for the top shortlist (OSINT).")
    ap.add_argument("file", help="ranked shortlist CSV (from rank_from_columns.py)")
    ap.add_argument("-o", "--out", default="reach.csv")
    ap.add_argument("--email-col", default="Email")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    run(a.file, a.out, a.email_col, a.top)
