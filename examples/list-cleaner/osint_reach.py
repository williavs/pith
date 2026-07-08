"""Stage 3 (OSINT): for the TOP shortlist only, find each decision-maker's OTHER public channels.

TWO signals, VERY different confidence — don't conflate them:

- gravatar_profile(email): PRECISE. Keyed on the email hash, so a hit is genuinely THIS person's
  linked accounts. The only identity-anchored signal here. (On business-owner lists it rarely hits
  — owners seldom use Gravatar — but when it does, trust it.)

- enumerate_profiles(handle): existence-only across ~480 sites, keyed on a derived NAME handle.
  This is a NAMESAKE generator, not identity confirmation. Measured: a fabricated common name
  ("davidthompson") "exists" on 145 sites — because *some* David Thompson registered each. A
  firstname+lastname handle collides with a stranger on nearly every major platform. So these are
  labeled `namesake_leads` (unverified) — eyeball candidates, NOT confirmed reach channels. Output
  is filtered to high-value hosts to keep the list short, and the pith control-probe already strips
  sites that 2xx every handle (airliners/apple), but the residual collision is fundamental to
  name-based enumeration and can't be tuned away. To actually reach a person, use the LinkedIn URL
  the list already carries, or a gravatar hit.

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


# Channels where finding a decision-maker is actually actionable for B2B outreach. Existence-only
# enumeration across ~480 sites is noisy (name collisions); restricting the OUTPUT to these kills
# the long tail (boardgamegeek, archive.org, hobby forums) that's never a real reach path.
_HIGH_VALUE = ("github.com", "gitlab.com", "twitter.com", "x.com", "keybase.io", "medium.com",
               "substack.com", "dev.to", "producthunt.com", "wellfound.com", "angel.co",
               "news.ycombinator.com", "kaggle.com", "codepen.io", "behance.net", "dribbble.com",
               "bsky.app", "mastodon", "youtube.com", "gumroad.com", "about.me")

# LinkedIn URL slugs carry a disambiguating hash suffix (brian-eggers-2b95a76). That whole string is
# NOT a username anyone reuses elsewhere — feeding it to enumeration is the source of cross-site
# false positives. A clean firstname+lastname handle is what people actually register.
_LI_HASH = re.compile(r"-[0-9a-f]{6,}$")


def _handle(row, email_col):
    """A real username to enumerate: firstname+lastname (what people register), then the LinkedIn
    slug with its hash suffix stripped, then the email local part. Never the raw hashed slug."""
    fn, ln = str(row.get("First Name", "")).strip(), str(row.get("Last Name", "")).strip()
    if fn and ln:
        h = re.sub(r"[^a-z0-9]", "", (fn + ln).lower())
        if len(h) >= 4:
            return h
    m = re.search(r"/in/([A-Za-z0-9\-]{3,})", str(row.get("Person Linkedin Url", "") or ""))
    if m:
        return _LI_HASH.sub("", m.group(1)).rstrip("-") or None
    local = str(row.get(email_col, "")).split("@")[0]
    return re.sub(r"[^a-z0-9]", "", local.lower()) or None


def _keep(url):
    return any(h in url for h in _HIGH_VALUE)


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
                allp = [p["url"] for p in (res.get("profiles") if isinstance(res, dict) else res) if p.get("url")]
                prof = [u for u in allp if _keep(u)]   # high-value channels only; drop the long-tail noise
            except Exception:
                pass
        rows.append({
            "Company": r.get("Company"), "name": f"{r.get('First Name','')} {r.get('Last Name','')}".strip(),
            "email": email, "linkedin": r.get("Person Linkedin Url", ""),
            "gravatar_channels": ", ".join(chans),           # PRECISE (email-anchored)
            "handle": h, "namesake_leads": ", ".join(prof[:8]),  # UNVERIFIED (name-collision — eyeball only)
        })
        print(f"  [{i+1}/{len(df)}] {rows[-1]['name'][:24]:24} gravatar:{len(chans)} namesakes:{len(prof)}", file=sys.stderr, flush=True)

    outdf = pd.DataFrame(rows)
    outdf.to_csv(os.path.expanduser(out), index=False)
    hit_g = (outdf["gravatar_channels"] != "").sum()
    hit_p = (outdf["namesake_leads"] != "").sum()
    print(f"\n{len(outdf)} contacts: gravatar (precise) hit {hit_g} ({100*hit_g//len(outdf)}%), "
          f"namesake leads (unverified) {hit_p} ({100*hit_p//len(outdf)}%) -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Find multi-channel reach for the top shortlist (OSINT).")
    ap.add_argument("file", help="ranked shortlist CSV (from rank_from_columns.py)")
    ap.add_argument("-o", "--out", default="reach.csv")
    ap.add_argument("--email-col", default="Email")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    run(a.file, a.out, a.email_col, a.top)
