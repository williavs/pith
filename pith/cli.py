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
    ap.add_argument("--match", metavar="SUBSTR", help="with --sitemap: keep only URLs containing this substring")
    ap.add_argument("--limit", type=int, help="with --sitemap: cap number of pages gathered")
    ap.add_argument("--format", choices=["md", "json", "table"], default="md", help="batch output format (default md)")
    ap.add_argument("--workers", type=int, default=1, help="batch: parallel fetches (default 1)")
    ap.add_argument("--full", action="store_true", help="include full page markdown")
    ap.add_argument("--js", action="store_true", help="force a real browser (JS-rendered / bot-protected pages)")
    args = ap.parse_args()

    render_js = True if args.js else "auto"
    ex = Extractor()

    if args.sitemap or args.from_file:
        targets = (read_sitemap(args.sitemap, match=args.match, limit=args.limit)
                   if args.sitemap else read_targets(args.from_file))
        if not targets:
            ap.error("no URLs found (check --sitemap/--match or the --from file)")
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
