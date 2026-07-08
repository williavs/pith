"""Stage 3 (OSINT): for the TOP shortlist only, find each decision-maker's OTHER public channels —
CORROBORATED to the actual person, not just namesakes.

The trap this example teaches you to avoid: raw enumerate_profiles(handle) is EXISTENCE-ONLY. A
derived firstname+lastname handle collides with a stranger on nearly every platform — a fabricated
"davidthompson" "exists" on 145 sites, because *some* David Thompson registered each. Surfacing
those as reach channels is false confidence.

pith's design already solves this: enumerate = candidates, resolve = confirmation. So we use
`resolve_person(handle, Target)` — it enumerates, then FETCHES each candidate and scores it against
the person (full name on the page + company domain + shared email/phone + a backlink to a known
anchor like their LinkedIn/Gravatar). Only profiles with >=2 independent corroborating signals come
back ACCEPTED, each with a confidence. A random David Thompson's github carries neither our contact's
company domain nor their email -> rejected. This is slower (it fetches candidates) but it's the
difference between "a David Thompson exists here" and "THIS person is reachable here."

Two anchored signals feed the corroboration:
- gravatar_profile(email): precise (email-hash) linked accounts — seeded as anchors so enumerate
  hits that backlink to them get confirmed.
- the LinkedIn URL the list already carries: another known-good anchor.

Run: uv run --with "pith[osint,js] @ git+https://github.com/williavs/pith.git@master" --with pandas \
     python examples/list-cleaner/osint_reach.py ranked.csv -o reach.csv --top 25
"""
import argparse
import os
import re
import sys

import pandas as pd
from pith.gravatar import gravatar_profile
from pith.resolve import Target, resolve_person


# LinkedIn URL slugs carry a disambiguating hash suffix (brian-eggers-2b95a76) — a URL id, not a
# username anyone reuses. A clean firstname+lastname is what people actually register elsewhere.
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


def _gravatar_anchors(email):
    """Precise (email-hash) linked accounts — used as corroboration anchors AND reported directly."""
    try:
        g = gravatar_profile(email)
    except Exception:
        return []
    if not g.get("exists"):
        return []
    return [a["url"] for a in (g.get("accounts") or []) if a.get("url")]


def run(path, out, email_col, top, workers):
    df = pd.read_csv(os.path.expanduser(path), low_memory=False).head(top)
    rows = []
    for i, r in df.iterrows():
        email = str(r.get(email_col, "")).strip()
        name = f"{r.get('First Name','')} {r.get('Last Name','')}".strip()
        linkedin = str(r.get("Person Linkedin Url", "") or "").strip()
        website = str(r.get("Website", "") or "").strip()

        grav = _gravatar_anchors(email)
        anchors = set(grav) | ({linkedin} if linkedin else set())
        tgt = Target(name=name, company=str(r.get("Company", "") or ""), website=website,
                     anchors=anchors, emails={email} if "@" in email else set(),
                     phones={str(r.get("Work Direct Phone", "") or "")} - {""})

        h = _handle(r, email_col)
        res = {"confidence": 0.0, "profiles": [], "best_channels": []}
        if h:
            try:
                res = resolve_person(h, tgt, workers=workers)   # enumerate -> fetch -> corroborate
            except Exception as e:
                print(f"    resolve error {name}: {e}", file=sys.stderr)

        confirmed = [p["url"] for p in res["profiles"]]         # ACCEPT-only (>=2 signals)
        rows.append({
            "Company": r.get("Company"), "name": name, "email": email, "linkedin": linkedin,
            "gravatar_channels": ", ".join(grav),               # precise, email-anchored
            "identity_confidence": res["confidence"],           # 0-1, strength of best corroboration
            "confirmed_profiles": ", ".join(confirmed),         # corroborated to THIS person
            "best_channels": ", ".join(res["best_channels"]),   # top reach sites, ranked
        })
        print(f"  [{i+1}/{len(df)}] {name[:24]:24} grav:{len(grav)} "
              f"confirmed:{len(confirmed)} conf:{res['confidence']}", file=sys.stderr, flush=True)

    outdf = pd.DataFrame(rows)
    outdf.to_csv(os.path.expanduser(out), index=False)
    hit_g = (outdf["gravatar_channels"] != "").sum()
    hit_c = (outdf["confirmed_profiles"] != "").sum()
    print(f"\n{len(outdf)} contacts: gravatar hit {hit_g} ({100*hit_g//len(outdf)}%), "
          f"corroborated reach {hit_c} ({100*hit_c//len(outdf)}%) -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Corroborated multi-channel reach for the top shortlist (OSINT).")
    ap.add_argument("file", help="ranked shortlist CSV (from rank_from_columns.py)")
    ap.add_argument("-o", "--out", default="reach.csv")
    ap.add_argument("--email-col", default="Email")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--workers", type=int, default=6, help="parallel candidate fetches per person")
    a = ap.parse_args()
    run(a.file, a.out, a.email_col, a.top, a.workers)
