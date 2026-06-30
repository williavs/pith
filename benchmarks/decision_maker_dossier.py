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
import html as _html
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

    html_path = Path(__file__).parent / "dossier.html"
    html_path.write_text(_render_html(results, ok, total_chars, total_ms, workers))
    print(f"html report       -> {html_path}")


TIER_COLOR = {"browser": "#7c3aed", "cheap": "#0891b2", "document": "#ca8a04"}


def _render_html(results, ok, total_chars, total_ms, workers):
    cards = []
    for label, url, tier, dt, n, title, body in results:
        color = TIER_COLOR.get(tier, "#555")
        miss = "" if n > 0 else "opacity:.55;"
        cards.append(f"""
        <div class="card" style="{miss}">
          <div class="head">
            <span class="badge" style="background:{color}">{tier}</span>
            <span class="label">{_html.escape(label)}</span>
            <span class="meta">{dt:.0f} ms · {n:,} chars</span>
          </div>
          <div class="title">{_html.escape(str(title or '—'))}</div>
          <a class="src" href="{_html.escape(url)}">{_html.escape(url)}</a>
          <pre>{_html.escape(body[:6000])}{'…' if len(body) > 6000 else ''}</pre>
        </div>""")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>pith dossier — {TARGET}</title>
<style>
  body {{ font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif; background:#0f1115; color:#e6e6e6; margin:0; padding:32px; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  .sub {{ color:#9aa0aa; margin-bottom:20px; }}
  .stats {{ display:flex; gap:24px; flex-wrap:wrap; background:#161a22; border:1px solid #232838; border-radius:10px; padding:16px 20px; margin-bottom:24px; }}
  .stat b {{ font-size:20px; display:block; }} .stat span {{ color:#9aa0aa; font-size:13px; }}
  .card {{ background:#161a22; border:1px solid #232838; border-radius:10px; padding:16px 18px; margin-bottom:16px; }}
  .head {{ display:flex; align-items:center; gap:12px; margin-bottom:6px; flex-wrap:wrap; }}
  .badge {{ color:#fff; font-size:11px; font-weight:600; padding:2px 9px; border-radius:20px; text-transform:uppercase; letter-spacing:.04em; }}
  .label {{ font-weight:600; }} .meta {{ color:#9aa0aa; font-size:13px; margin-left:auto; }}
  .title {{ color:#c8cdd6; font-size:14px; margin:2px 0; }}
  .src {{ color:#5b9bd5; font-size:12px; text-decoration:none; word-break:break-all; }}
  pre {{ background:#0c0e13; border:1px solid #1d2230; border-radius:8px; padding:12px; margin-top:10px;
        max-height:280px; overflow:auto; white-space:pre-wrap; word-break:break-word; font-size:12.5px; color:#cdd3dc; }}
</style></head><body>
  <h1>Decision-maker dossier — {_html.escape(TARGET)}</h1>
  <div class="sub">pith assembled this from {len(results)} live public sources across 4 fetch tiers. No API keys. Public data only.</div>
  <div class="stats">
    <div class="stat"><b>{ok}/{len(results)}</b><span>sources with content</span></div>
    <div class="stat"><b>{total_chars:,}</b><span>chars of signal</span></div>
    <div class="stat"><b>{total_ms/1000:.1f}s</b><span>wall-clock (workers={workers})</span></div>
    <div class="stat"><b>4</b><span>tiers: browser · cheap · impersonation · document</span></div>
  </div>
  {''.join(cards)}
</body></html>"""


if __name__ == "__main__":
    w = 1
    if "--workers" in sys.argv:
        w = int(sys.argv[sys.argv.index("--workers") + 1])
    run(workers=w)
