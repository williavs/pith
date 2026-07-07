"""Batch contact-list cleanup + validation for a stale B2B list — the "I have 100k old leads,
which are still worth selling to?" job. Handles the whole file on disk with pith's deterministic
validators; NO live crawling (too slow at scale). Produces cleaned.csv + summary.json.

Tiers, cheapest first:
  1. offline, every row   — email syntax + role/disposable/freemail (pith.verify_email),
                            phone valid/region/line-type/E.164 (pith.phone_intel)
  2. deduped by domain    — deliverability: does the email domain resolve + have an MX record?
                            (24k unique domains for a 73k list — the whole point of deduping)
  3. (skipped at scale)   — LinkedIn/site/company checks are walled + slow; do those on a shortlist

Then a transparent `quality` tag (sellable / risky / dead) you can filter — no hidden score.

Run:
  uv run --with pandas --with openpyxl --with dnspython python examples/list-cleaner/clean.py \
      "~/Downloads/contacts.xlsx" -o cleaned.csv
  # dnspython is optional; without it MX is skipped and deliverability falls back to domain-resolves.
"""
import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pith import verify_email                     # noqa: E402
from pith.phoneintel import phone_intel           # noqa: E402


def _log(msg):
    print(f"[clean] {msg}", file=sys.stderr, flush=True)


def check_domains(domains, workers=50):
    """Deliverability per UNIQUE domain (dedup is the speedup): {domain: (resolves, has_mx)}.
    Parallel DNS; has_mx is None when dnspython isn't installed."""
    from pith.extract import _domain_resolves, _domain_has_mx

    def one(d):
        return d, (_domain_resolves(d), _domain_has_mx(d))
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (d, res) in enumerate(pool.map(one, domains), 1):
            out[d] = res
            if i % 2000 == 0:
                _log(f"  deliverability {i}/{len(domains)} domains")
    return out


def _site_domain(url):
    """A website URL/domain -> bare host (no scheme/www/path). '' if unusable."""
    import urllib.parse
    u = str(url).strip()
    if not u or u.lower() in ("nan", "none"):
        return ""
    host = urllib.parse.urlsplit(u if "//" in u else "//" + u).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _site_live(domain, timeout=6):
    """Does the domain serve a live website? HEAD (then GET) https, then http; 2xx/3xx = live.
    Bounded so a dead/hostile host fails fast. Best-effort — some live sites block bots (-> False)."""
    import urllib.request
    for scheme in ("https://", "http://"):
        for method in ("HEAD", "GET"):
            try:
                req = urllib.request.Request(scheme + domain, method=method,
                                             headers={"User-Agent": "Mozilla/5.0 pith-listcleaner"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return 200 <= r.status < 400
            except urllib.error.HTTPError as e:
                return e.code < 400 or e.code in (401, 403, 405, 429)   # answered = server is up
            except Exception:
                continue
    return False


def check_websites(domains, workers=40):
    """Website liveness per UNIQUE domain (deduped): {domain: live_bool}. HTTP, so slower than
    the DNS checks — dedup + bound is what makes it feasible at list scale."""
    out = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (d, live) in enumerate(pool.map(lambda d: (d, _site_live(d)), domains), 1):
            out[d] = live
            if i % 1000 == 0:
                _log(f"  website liveness {i}/{len(domains)} domains")
    return out


def _quality(row) -> str:
    """Transparent sell-ability tier — filterable, not a black-box score."""
    if not row["email_syntax"] or row["is_disposable"]:
        return "dead"
    mx = row["has_mx"]
    if mx is False or (mx is None and not row["domain_resolves"]):
        return "dead"                        # domain won't take mail / doesn't exist
    if row["is_role"] or row["is_freemail"]:
        return "risky"                       # deliverable but generic/personal, not the owner's biz inbox
    return "sellable"


def clean(path, email_col, phone_cols, out_csv, website_col=None, workers=50, limit=None, trim=True):
    import pandas as pd

    t0 = time.time()
    _log(f"reading {path}")
    phone_cols = [c.strip() for c in (phone_cols or "").split(",") if c.strip()]
    # force email/phone/website to string — else read_csv/xlsx parses '+12817682900' as int64 and
    # drops the '+', breaking E.164 phone validation (and mangles long IDs / leading-zero values).
    strcols = {c: str for c in ([email_col] + phone_cols + ([website_col] if website_col else []))}
    df = (pd.read_excel(path, dtype=strcols) if str(path).lower().endswith((".xlsx", ".xls"))
          else pd.read_csv(path, dtype=strcols))
    if limit:
        df = df.head(limit)
    n = len(df)
    _log(f"{n:,} rows")

    # --- Tier 1: offline, every row ---
    _log("tier 1: email syntax + phone validity (offline)")
    ev = [verify_email(str(e)) if pd.notna(e) else {"valid_syntax": False} for e in df[email_col]]
    df["email_syntax"] = [x.get("valid_syntax", False) for x in ev]
    df["is_role"] = [x.get("is_role", False) for x in ev]
    df["is_disposable"] = [x.get("is_disposable", False) for x in ev]
    df["is_freemail"] = [x.get("is_freemail", False) for x in ev]
    df["email_domain"] = [x.get("domain", "") for x in ev]

    # phone: coalesce the first non-empty across the given phone columns (Apollo lists have several)
    present = [c for c in phone_cols if c in df.columns]
    if present:
        best = df[present].apply(lambda r: next((str(v) for v in r if pd.notna(v) and str(v).strip()), ""), axis=1)
        pi = [phone_intel(p) if p else {} for p in best]
        df["phone_best"] = best
        df["phone_valid"] = [x.get("valid", False) for x in pi]
        df["phone_e164"] = [x.get("e164", "") for x in pi]
        df["phone_region"] = [x.get("region", "") for x in pi]
        df["phone_line_type"] = [x.get("line_type", "") for x in pi]

    # --- Tier 2: email deliverability, deduped by domain ---
    domains = sorted({d for d in df["email_domain"] if d})
    _log(f"tier 2: email deliverability on {len(domains):,} unique domains (of {n:,} rows)")
    dmap = check_domains(domains, workers=workers) if domains else {}
    df["domain_resolves"] = [dmap.get(d, (False, None))[0] for d in df["email_domain"]]
    df["has_mx"] = [dmap.get(d, (False, None))[1] for d in df["email_domain"]]

    # --- Tier 2b: website liveness (only when a website column exists), deduped by domain ---
    if website_col and website_col in df.columns:
        df["website_domain"] = [_site_domain(u) for u in df[website_col]]
        wdoms = sorted({d for d in df["website_domain"] if d})
        _log(f"tier 2b: website liveness on {len(wdoms):,} unique sites")
        wmap = check_websites(wdoms, workers=max(20, workers // 2)) if wdoms else {}
        df["website_live"] = [wmap.get(d, False) if d else "" for d in df["website_domain"]]

    # --- dedup + quality ---
    el = df[email_col].astype(str).str.lower()
    df["is_duplicate_email"] = el.duplicated(keep="first") & el.ne("nan")
    df["quality"] = df.apply(_quality, axis=1)

    df.to_csv(out_csv, index=False)
    summary = _summarize(df, n, time.time() - t0)
    Path(out_csv).with_suffix(".summary.json").write_text(json.dumps(summary, indent=2))
    _log(f"wrote {out_csv} + summary in {summary['elapsed_s']}s")

    if trim:  # trimmed = the fat cut off: deliverable, deduped contacts you'd actually work
        keep = df[(df["quality"] != "dead") & (~df["is_duplicate_email"])]
        trim_path = str(Path(out_csv).with_suffix("")) + ".trimmed.csv"
        keep.to_csv(trim_path, index=False)
        _log(f"trimmed {n:,} -> {len(keep):,} contactable ({100*len(keep)//n if n else 0}%) -> {trim_path}")
        summary["trimmed_rows"] = len(keep)

    print(json.dumps(summary, indent=2))
    return summary


def _summarize(df, n, elapsed):
    def rate(mask):
        return {"n": int(mask.sum()), "pct": round(100 * mask.mean(), 1)}
    q = df["quality"].value_counts().to_dict()
    s = {
        "rows": n, "elapsed_s": round(elapsed, 1),
        "quality": {k: int(v) for k, v in q.items()},
        "email_valid_syntax": rate(df["email_syntax"]),
        "email_disposable": rate(df["is_disposable"]),
        "email_role": rate(df["is_role"]),
        "email_freemail": rate(df["is_freemail"]),
        "domain_resolves": rate(df["domain_resolves"]),
        "duplicate_email": rate(df["is_duplicate_email"]),
    }
    if "has_mx" in df:
        s["email_has_mx"] = rate(df["has_mx"] == True)  # noqa: E712 (None/False both excluded)
    if "phone_valid" in df:
        s["phone_valid"] = rate(df["phone_valid"])
        # phonenumbers can't split mobile/fixed for NANP (returns fixed_or_mobile), so report the
        # distribution rather than a single misleading "mobile %".
        s["phone_line_types"] = {k: int(v) for k, v in df.loc[df["phone_valid"], "phone_line_type"].value_counts().items()}
    if "website_live" in df:
        s["website_live"] = rate(df["website_live"] == True)  # noqa: E712
    s["sellable_pct"] = round(100 * (df["quality"] == "sellable").mean(), 1)
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Validate + clean a stale contact list (email/phone/website/deliverability).")
    ap.add_argument("file", help="xlsx or csv contact list")
    ap.add_argument("-o", "--out", default="cleaned.csv", help="output CSV (default cleaned.csv)")
    ap.add_argument("--email-col", default="email")
    ap.add_argument("--phone-col", default="sanitized_phone", help="phone column(s), comma-separated -> first non-empty wins")
    ap.add_argument("--website-col", default=None, help="website column to verify liveness (optional)")
    ap.add_argument("--workers", type=int, default=50, help="parallel lookups (default 50)")
    ap.add_argument("--no-trim", action="store_true", help="skip writing the trimmed (contactable-only) CSV")
    ap.add_argument("--limit", type=int, default=None, help="cap rows (for testing)")
    args = ap.parse_args()
    clean(os.path.expanduser(args.file), args.email_col, args.phone_col, args.out,
          website_col=args.website_col, workers=args.workers, limit=args.limit, trim=not args.no_trim)
