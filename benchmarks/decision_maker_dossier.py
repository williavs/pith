"""Decision-maker dossier — the real sales use case, pushed to its limits.

A BDR wants everything public on ONE decision-maker + their company before outreach.
The signals live across wildly different source types: walled social (LinkedIn, Instagram,
Reddit, X), B2B intel (Crunchbase, Indeed, Glassdoor, Trustpilot), normal news, a paywall
that 403s plain HTTP, and a PDF report. pith routes each through the right tier:

    document  -> MarkItDown            (PDF/Office)
    browser   -> scrapling stealth     (walled gardens, ~3-8s)
    cheap     -> static, then curl_cffi impersonation if static 403s (~0.2-0.6s)

This gathers the lot, reports per-source tier/latency/bytes/status, and writes the
assembled markdown corpus a salesperson (or an LLM) would synthesize from.

Run:  ../.venv/bin/python decision_maker_dossier.py [--workers N]
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pith import Extractor
from pith.core import _is_document, _needs_browser

TARGET = "Matt MacInnis — Chief Product Officer, Rippling"

# (label, url) — real public sources, spanning every tier
SOURCES = [
    # walled social — the highest-value intent signals, only the browser reaches them
    ("LinkedIn post (AI launch)", "https://www.linkedin.com/posts/roshan-oommen-6a87131a3_ai-futureofwork-hrtech-activity-7460001797101842433-k0e-"),
    ("Instagram reel (prototype)", "https://www.instagram.com/reel/DW4jJasiOwH"),
    ("Reddit AMA (CPO, verbatim)", "https://www.reddit.com/r/rippling/comments/1sll2br/im_matt_macinnis_chief_product_officer_at"),
    ("X / Rippling", "https://x.com/Rippling"),
    # B2B sales-intel
    ("Crunchbase (funding/firmographics)", "https://www.crunchbase.com/organization/rippling"),
    ("Indeed (hiring intent)", "https://www.indeed.com/cmp/Rippling/jobs"),
    ("Glassdoor (company overview)", "https://www.glassdoor.com/Overview/Working-at-Rippling-EI_IE2452185.11,19.htm"),
    ("Trustpilot (reviews)", "https://www.trustpilot.com/review/rippling.com"),
    # normal pages — fast static path
    ("Company site", "https://www.rippling.com/"),
    ("Company blog", "https://www.rippling.com/blog"),
    # paywall that 403s plain HTTP — rescued by the impersonation tier
    ("WSJ tech (impersonation tier)", "https://www.wsj.com/tech"),
    # a document — PDF -> markdown via MarkItDown
    ("Industry report (PDF)", "https://arxiv.org/pdf/1706.03762.pdf"),
]


def expected_tier(url: str) -> str:
    if _is_document(url):
        return "document"
    if _needs_browser(url):
        return "browser"
    return "cheap"


def run(workers: int = 1):
    ex = Extractor()
    print(f"DOSSIER: {TARGET}\n{'='*70}")
    rows, corpus = [], [f"# Dossier — {TARGET}\n"]
    t_all = time.perf_counter()

    def one(item):
        label, url = item
        t = time.perf_counter()
        out = ex.extract(urls=[url])
        dt = (time.perf_counter() - t) * 1000
        if out.results and out.results[0].excerpts:
            body = out.results[0].excerpts[0]
            return (label, url, expected_tier(url), dt, len(body), out.results[0].title, body)
        err = out.errors[0]["error"] if out.errors else "empty"
        return (label, url, expected_tier(url), dt, 0, None, f"[no content: {err[:60]}]")

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, SOURCES))
    else:
        results = [one(s) for s in SOURCES]

    total_ms = (time.perf_counter() - t_all) * 1000
    print(f"{'TIER':10} {'ms':>6} {'chars':>7}  source")
    ok = 0
    for label, url, tier, dt, n, title, body in results:
        status = "ok " if n > 0 else "MISS"
        if n > 0:
            ok += 1
        print(f"{tier:10} {dt:6.0f} {n:>7}  {status} {label}")
        rows.append((label, tier, n))
        if n > 0:
            corpus.append(f"\n## {label}\n_source: {url}_\n\n{body}\n")

    by_tier = {}
    for label, tier, n in rows:
        d = by_tier.setdefault(tier, [0, 0, 0])  # sources, hits, chars
        d[0] += 1
        d[1] += 1 if n else 0
        d[2] += n
    print(f"\n{'-'*70}")
    print(f"coverage: {ok}/{len(SOURCES)} sources yielded content")
    for tier, (s, h, c) in sorted(by_tier.items()):
        print(f"  {tier:10} {h}/{s} hits, {c:,} chars")
    total_chars = sum(n for _, _, n in rows)
    print(f"total corpus: {total_chars:,} chars  ·  wall-clock {total_ms/1000:.1f}s (workers={workers})")

    out_path = Path(__file__).parent / "dossier_output.md"
    out_path.write_text("\n".join(corpus))
    print(f"assembled dossier -> {out_path}  ({total_chars:,} chars of synthesizable signal)")


if __name__ == "__main__":
    w = 1
    if "--workers" in sys.argv:
        w = int(sys.argv[sys.argv.index("--workers") + 1])
    run(workers=w)
