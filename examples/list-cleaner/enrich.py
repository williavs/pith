"""Stage 2: turn a CLEAN contact list into a RANKED account list. Dedupe contacts to unique
companies, enrich each with pith's signal stack (tech / hiring / news / funding), score for
sell-fit, write a ranked CSV. Checkpointed + resumable — the enrichment is network-bound and slow,
so you never lose progress or re-hit a company you already did.

Why Python (not a "faster" language): 450k rows is small — pandas handles it trivially. The work is
network-bound pith calls, which ARE Python. A rewrite buys nothing; deduping + checkpointing does.

Pipeline:
  clean.py  ->  <cleaned>.trimmed.csv  ->  enrich.py  ->  accounts.csv (ranked)

Run:
  uv run --with pandas python examples/list-cleaner/enrich.py ~/hfl-contacts/verified_40k.trimmed.csv \
      -o ~/hfl-contacts/accounts_40k.csv --limit 300 --workers 6
  # --limit caps how many top companies to enrich (by contact count) — enrich your target set, not all.
"""
import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ACCOUNT_COLS = ["domain", "company", "contacts", "tech", "modernness", "open_roles", "ats",
                "signals", "funding", "score"]


def _log(m):
    print(f"[enrich] {m}", file=sys.stderr, flush=True)


def enrich_company(domain, name):
    """One company -> a signal dossier. Every pith call guarded; a dead source never sinks the row."""
    from pith.cli import website_intel
    from pith.jobs import jobs_search
    from pith.news import news_search
    from pith.financials import company_intel

    d = {c: "" for c in ACCOUNT_COLS}
    d.update(domain=domain, company=name, open_roles=0)
    url = "https://" + domain
    try:
        wi = website_intel(url)
        d["tech"], d["modernness"] = wi.get("framework") or wi.get("builder") or "", wi.get("modernness_grade") or ""
    except Exception:
        pass
    try:
        j = jobs_search(name, domain, render=False)   # render=False: ATS-API hiring counts, NO per-company
        d["open_roles"], d["ats"] = j.get("count", 0), j.get("ats") or ""   # browser (browser tier = ~8min/co at batch scale)
    except Exception:
        pass
    try:
        tags = {}
        for it in news_search(name, domain=domain, window_days=120):
            s = it.get("signal")
            if s and s != "news":
                tags[s] = tags.get(s, 0) + 1
        d["signals"] = " ".join(f"{k}:{v}" for k, v in sorted(tags.items(), key=lambda x: -x[1]))
    except Exception:
        pass
    try:
        ci = company_intel(name)
        raises = (ci.get("funding") or {}).get("raises") or []
        if ci.get("kind") == "us_public":
            d["funding"] = "public"
        elif raises:
            r = max(raises, key=lambda x: float(x.get("total_sold") or 0))
            d["funding"] = f"raised {r.get('total_sold')}"
    except Exception:
        pass
    d["score"] = _score(d)
    return d


def _score(d):
    """Transparent sell-fit score (not a black box) — funded + hiring + has-news + modern all raise it."""
    s = 0
    s += min(int(d.get("open_roles") or 0), 20) * 2                 # hiring = building = needs software
    s += 15 * ("fund" in (d.get("signals") or "") or bool(d.get("funding")))   # budget
    s += 5 * sum(t in (d.get("signals") or "") for t in ("leadership", "product", "ai", "expansion"))
    s += 5 * (d.get("modernness") in ("A", "B"))
    return s


def _domains(df, domain_col, name_col):
    """Contacts -> unique companies (domain -> (name, contact_count)), busiest first."""
    import pandas as pd
    counts = {}
    for dom, nm in zip(df[domain_col].fillna(""), df[name_col].fillna("") if name_col in df else [""] * len(df)):
        dom = str(dom).strip().lower()
        if not dom or dom == "nan":
            continue
        c = counts.setdefault(dom, {"name": str(nm), "n": 0})
        c["n"] += 1
    return sorted(((d, v["name"], v["n"]) for d, v in counts.items()), key=lambda x: -x[2])


def run(path, out, domain_col, name_col, limit, workers):
    import pandas as pd

    df = pd.read_csv(os.path.expanduser(path))
    companies = _domains(df, domain_col, name_col)
    _log(f"{len(df):,} contacts -> {len(companies):,} unique companies")
    if limit:
        companies = companies[:limit]
        _log(f"enriching top {len(companies):,} by contact count")

    out = os.path.expanduser(out)
    done = set()
    if os.path.exists(out):                      # resume: skip companies already enriched
        done = set(pd.read_csv(out)["domain"].astype(str))
        _log(f"resuming — {len(done):,} already done")
    todo = [c for c in companies if c[0] not in done]

    header_needed = not os.path.exists(out)
    with open(out, "a") as fh, ThreadPoolExecutor(max_workers=workers) as pool:
        if header_needed:
            fh.write(",".join(ACCOUNT_COLS) + "\n")
        futs = {pool.submit(enrich_company, d, nm): (d, n) for d, nm, n in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            dom, cnt = futs[fut]
            try:
                r = fut.result()
                r["contacts"] = cnt
            except Exception as e:
                r = {c: "" for c in ACCOUNT_COLS}; r.update(domain=dom, contacts=cnt, company=f"error: {e}")
            fh.write(",".join(_csv(r[c]) for c in ACCOUNT_COLS) + "\n")
            fh.flush()                           # checkpoint every row — safe to Ctrl-C + resume
            if i % 25 == 0:
                _log(f"  {i}/{len(todo)} enriched")

    # re-sort the final file by score
    final = pd.read_csv(out).sort_values("score", ascending=False)
    final.to_csv(out, index=False)
    _log(f"done -> {out} ({len(final):,} accounts, ranked by score)")
    print(final.head(15).to_string(index=False))


def _csv(v):
    s = str(v).replace('"', "'")
    return f'"{s}"' if ("," in s or "\n" in s) else s


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Enrich + rank the companies behind a clean contact list.")
    ap.add_argument("file", help="cleaned/trimmed contact CSV (from clean.py)")
    ap.add_argument("-o", "--out", default="accounts.csv")
    ap.add_argument("--domain-col", default="email_domain", help="company domain column (clean.py adds email_domain)")
    ap.add_argument("--name-col", default="organization_name", help="company name column")
    ap.add_argument("--limit", type=int, default=300, help="enrich the top N companies by contact count (0 = all)")
    ap.add_argument("--workers", type=int, default=6, help="parallel company enrichments")
    a = ap.parse_args()
    t0 = time.time()
    run(a.file, a.out, a.domain_col, a.name_col, a.limit or None, a.workers)
    _log(f"elapsed {time.time()-t0:.0f}s")
