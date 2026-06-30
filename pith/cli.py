"""pith CLI.

Single URL:   pith <url> [objective] [--full] [--js]
A list:       pith --from companies.csv [--format md|json|table] [--workers N]

The list file is one target per line: a bare URL, or a label+URL pair (csv, either
order — the http field is the URL). '#' lines and blanks are skipped.
"""
import argparse
import csv
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from .core import Extractor, Result


def read_sitemap(url: str, match: str | None = None, limit: int | None = None) -> list[tuple[str | None, str]]:
    """Gather a whole doc site: fetch sitemap.xml, return its <loc> URLs as (None, url) targets.
    `match` keeps only locs containing that substring (e.g. '/router/' for one section).
    Follows a <sitemapindex> one level deep. `limit` caps the result (and warns on the cap)."""
    def fetch(u: str) -> str:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 pith"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

    def locs(xml: str) -> list[str]:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)

    xml = fetch(url)
    found = locs(xml)
    # a sitemap index lists child sitemaps, not pages — recurse one level
    if "<sitemapindex" in xml:
        pages: list[str] = []
        for child in found:
            try:
                pages.extend(locs(fetch(child)))
            except Exception:  # ponytail: one bad child sitemap shouldn't sink the crawl
                continue
        found = pages
    if match:
        found = [u for u in found if match in u]
    seen: set[str] = set()
    uniq = [u for u in found if not (u in seen or seen.add(u))]
    if limit and len(uniq) > limit:
        print(f"sitemap: {len(uniq)} urls, capping to --limit {limit}", file=sys.stderr)
        uniq = uniq[:limit]
    return [(None, u) for u in uniq]


# GTM-relevant sections: where decision-maker signal lives on a company site.
_SECTIONS = ("about", "contact", "team", "leadership", "people", "our-team",
             "company", "management", "founders", "staff", "careers", "jobs")


def score_relevance(query: str, url: str, snippet: str = "") -> int:
    """Buyer-signal relevance of a candidate, pre-fetch: how many query tokens appear in the
    URL + its search/anchor snippet. The gate's job is identity matching (is this about THIS
    target), which is lexical — and this beat a 270MB semantic embedder 1.00 vs 0.83 on the
    labeled dossier set (benchmarks/2026-06-30-gate-scorer.md). Generic, deterministic, no
    hardcoded priors, no model. Feed a snippet when you have one — that's where the lift is."""
    toks = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2}
    hay = (url + " " + snippet).lower()
    return sum(t in hay for t in toks)


def gate(targets, query: str, budget: int | None = None, snippets: dict | None = None):
    """Spend the fetch budget on the highest-signal candidates: rank (label,url) targets by
    score_relevance desc, keep the top `budget`. Stable for ties (preserves input order)."""
    snippets = snippets or {}
    ranked = sorted(targets, key=lambda t: score_relevance(query, t[1], snippets.get(t[1], "")),
                    reverse=True)
    return ranked[:budget] if budget else ranked


def _section_links(seed: str, html: str, sections, limit: int) -> list[tuple[str | None, str]]:
    """Pure: from a homepage's HTML, keep same-domain links whose path hits a section.
    Seed first, then matches in document order, deduped, capped. (Tested offline.)"""
    from urllib.parse import urljoin, urlsplit
    host = urlsplit(seed).netloc
    out, seen = [(None, seed)], {seed}
    for href in re.findall(r'href=["\']([^"\']+)', html):
        u = urljoin(seed, href).split("#")[0]
        sp = urlsplit(u)
        if sp.netloc == host and any(s in sp.path.lower() for s in sections) and u not in seen:
            seen.add(u)
            out.append((None, u))
            if len(out) >= limit:
                break
    return out


def crawl_site(seed: str, sections=_SECTIONS, limit: int = 25) -> list[tuple[str | None, str]]:
    """Strategic crawl: fetch a homepage, follow one level of same-domain links into the
    high-value sections (about/contact/team/...). One level — nav links cover the GTM
    sections, and walled pages cost ~4-5s each so coverage is the wrong goal anyway.
    ponytail: one level; recurse if a real site buries its team page deeper than nav."""
    req = urllib.request.Request(seed, headers={"User-Agent": "Mozilla/5.0 pith"})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
    return _section_links(seed, html, sections, limit)


def read_targets(path: str) -> list[tuple[str | None, str]]:
    """Parse a URL-list file into (label, url) pairs. Bare URL -> label None.
    Handles plain .txt (one URL per line) and .csv (label,url or url,label)."""
    targets: list[tuple[str | None, str]] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row if c.strip()]
            if not cells or cells[0].startswith("#"):
                continue
            url = next((c for c in cells if c.startswith(("http://", "https://"))), None)
            if not url:  # ponytail: skip junk lines, don't sink the batch
                continue
            label = next((c for c in cells if c != url), None)
            targets.append((label, url))
    return targets


def run_batch(ex, targets, *, objective, full, render_js, workers):
    """Drive the extractor over targets, one extract() per URL so we can show progress
    and parallelize. Returns (label, url, Result | error-dict) rows in input order."""
    total = len(targets)

    def one(item):
        i, (label, url) = item
        print(f"[{i}/{total}] {label or url}", file=sys.stderr, flush=True)
        out = ex.extract(urls=[url], objective=objective, full_content=full, render_js=render_js)
        return (label, url, out.results[0] if out.results else out.errors[0])

    items = list(enumerate(targets, 1))
    if workers > 1:
        # ponytail: thread the fetches; the stealth browser launches per-call so it's
        # thread-safe enough here. Drop --workers to 1 if a site gets flaky under load.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(one, items))
    return [one(it) for it in items]


def render(rows, fmt: str) -> str:
    ok = [(l, u, r) for l, u, r in rows if isinstance(r, Result)]
    err = [(l, u, r) for l, u, r in rows if not isinstance(r, Result)]

    if fmt == "json":
        return json.dumps({
            "results": [{"label": l, **asdict(r)} for l, u, r in ok],
            "errors": [{"label": l, "url": u, "error": r.get("error")} for l, u, r in err],
        }, indent=2)

    if fmt == "table":
        out = [f"{'STATUS':<7} {'BYTES':>7}  TARGET"]
        for l, u, r in rows:
            if isinstance(r, Result):
                n = len(r.full_content or (r.excerpts[0] if r.excerpts else ""))
                out.append(f"{'ok':<7} {n:>7}  {l or u}")
            else:
                out.append(f"{'ERROR':<7} {'-':>7}  {l or u}: {str(r.get('error'))[:50]}")
        out.append(f"\n{len(ok)} ok, {len(err)} errors")
        return "\n".join(out)

    # markdown (default)
    out = []
    for l, u, r in ok:
        out.append(f"## {l}" if l else f"## {u}")
        if r.title:
            out.append(f"# {r.title}")
        if r.publish_date:
            out.append(f"_{r.publish_date}_")
        out.append("")
        out.extend(r.excerpts)
        out.append("")
    for l, u, r in err:
        out.append(f"## {l or u}\n[error] {r.get('error')}\n")
    out.append(f"---\n_{len(ok)} ok, {len(err)} errors_")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(prog="pith", description="URL -> clean LLM-ready markdown (free).")
    ap.add_argument("url", nargs="?", help="a single URL (omit when using --from)")
    ap.add_argument("objective", nargs="?", help="optional: return only passages answering this (needs GROQ_API_KEY)")
    ap.add_argument("--from", dest="from_file", metavar="FILE", help="batch: read URLs from a list file (txt or csv)")
    ap.add_argument("--sitemap", metavar="URL", help="batch: crawl a sitemap.xml and gather every page (filter with --match)")
    ap.add_argument("--crawl", metavar="URL", help="batch: from a homepage, follow links into about/contact/team/... sections")
    ap.add_argument("--match", metavar="SUBSTR", help="with --sitemap: keep only URLs containing this substring")
    ap.add_argument("--limit", type=int, default=25, help="cap pages gathered by --sitemap/--crawl (default 25)")
    ap.add_argument("--about", metavar="QUERY", help="batch: rank candidates by relevance to this (e.g. a target name+company) and fetch the most relevant first")
    ap.add_argument("--budget", type=int, help="with --about: fetch only the top-N most relevant candidates (skip the rest — saves the 4-5s/page walled-fetch cost)")
    ap.add_argument("--format", choices=["md", "json", "table"], default="md", help="batch output format (default md)")
    ap.add_argument("--workers", type=int, default=1, help="batch: parallel fetches (default 1)")
    ap.add_argument("--full", action="store_true", help="include full page markdown")
    ap.add_argument("--js", action="store_true", help="force a real browser (JS-rendered / bot-protected pages)")
    args = ap.parse_args()

    render_js = True if args.js else "auto"
    ex = Extractor()

    if args.sitemap or args.crawl or args.from_file:
        if args.sitemap:
            targets = read_sitemap(args.sitemap, match=args.match, limit=args.limit)
        elif args.crawl:
            targets = crawl_site(args.crawl, limit=args.limit)
        else:
            targets = read_targets(args.from_file)
        if not targets:
            ap.error("no URLs found (check --sitemap/--match or the --from file)")
        if args.about:  # fetch-budget gate: rank by relevance, keep top --budget
            n = len(targets)
            targets = gate(targets, args.about, budget=args.budget)
            print(f"gate: ranked {n} candidates by '{args.about}'"
                  + (f", fetching top {args.budget}" if args.budget else ""), file=sys.stderr)
        rows = run_batch(ex, targets, objective=args.objective, full=args.full,
                         render_js=render_js, workers=args.workers)
        print(render(rows, args.format))
        return

    if not args.url:
        ap.error("provide a URL, or --from FILE for a list")

    out = ex.extract(urls=[args.url], objective=args.objective, full_content=args.full, render_js=render_js)
    for r in out.results:
        if r.title:
            print(f"# {r.title}")
        if r.publish_date:
            print(f"_{r.publish_date}_\n")
        for e in r.excerpts:
            print(e)
    for err in out.errors:
        print(f"[error] {err['url']}: {err['error']}")


if __name__ == "__main__":
    main()
