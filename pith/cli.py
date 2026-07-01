"""pith CLI.

Single URL:   pith <url> [--full] [--js]
A list:       pith --from companies.csv [--format md|json|table] [--workers N]

The list file is one target per line: a bare URL, or a label+URL pair (csv, either
order — the http field is the URL). '#' lines and blanks are skipped.
"""
import argparse
import csv
import json
import logging
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from .core import Extractor, Result, _needs_browser, _BROWSER_MAX_CONCURRENCY

log = logging.getLogger("pith")


class _JsonFmt(logging.Formatter):
    """One compact JSON object per log record: the message is the `event`, any structured
    `extra=` fields ride alongside. No deps — stdlib logging + json."""
    _STD = set(logging.makeLogRecord({}).__dict__) | {"taskName", "message"}

    def format(self, rec):
        d = {"event": rec.getMessage()}
        for k, v in rec.__dict__.items():
            if k not in self._STD and k not in ("msg", "args"):
                d[k] = v
        return json.dumps(d, default=str)


def _enable_trace():
    """--verbose: stream every pipeline/network step as NDJSON on stderr (results stay on
    stdout). Surfaces pith's tier/timing/concurrency events plus scrapling's network logs."""
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(_JsonFmt())
    for name, lvl in (("pith", logging.DEBUG), ("scrapling", logging.INFO)):
        lg = logging.getLogger(name)
        lg.handlers[:] = [h]
        lg.setLevel(lvl)
        lg.propagate = False


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


# --- GTM company enrichment: bare company list -> structured rows a rep can act on ---

def _registrable(url: str) -> str:
    from urllib.parse import urlsplit
    host = urlsplit(url if "//" in url else "//" + url).netloc.lower().split(":")[0]
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _name_toks(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 2]


def _company_social(socials, name: str, host_key: str):
    """Pick the company's own profile on a platform: the one whose handle matches the company
    name. Returns None rather than guess — avoids the personal-account false positive
    (github.com/1rgs for 'Ramp')."""
    toks = _name_toks(name)
    for s in socials:
        if host_key not in s.lower():
            continue
        handle = s.rstrip("/").rsplit("/", 1)[-1].lower()
        if any(t in handle or handle in t for t in toks):
            return s
    return None


def _company_emails(emails, website: str) -> list[str]:
    """Keep only emails on the company's own domain — a company-domain address is a real
    contact; an off-domain one (kevin@encom.com on linear.app) is demo/third-party noise."""
    dom = _registrable(website)
    return [e for e in emails if e.split("@")[-1].lower().endswith(dom)]


def enrich_company(name: str, website: str, workers: int = 4) -> dict:
    """One pith pass over a company's key sections -> a GTM-ready row. All browser/tier/
    concurrency machinery hidden; caller just gets structured, company-matched data."""
    ex = Extractor()
    targets = crawl_site(website, limit=6)
    out = ex.extract([u for _, u in targets], concurrency=workers, render_js="auto")
    socials, emails = set(), set()
    for r in out.results:
        socials |= set(r.socials)
        emails |= set(r.emails)
    urls = [r.url for r in out.results]
    return {
        "company": name, "website": website, "pages": len(out.results),
        "linkedin": _company_social(socials, name, "linkedin.com/company"),
        "github": _company_social(socials, name, "github.com"),
        "twitter": _company_social(socials, name, "twitter.com") or _company_social(socials, name, "x.com"),
        "emails": _company_emails(emails, website),
        "careers": any("career" in u.lower() or "/job" in u.lower() for u in urls),
    }


# email value order for GTM: an owner-operator's freemail beats a named person on the
# company domain beats a generic role mailbox. Disposable/invalid are dropped.
_EMAIL_RANK = {"owner": 0, "person": 1, "role": 2, "other": 3}


def _email_type(email: str, domain: str) -> str:
    from .extract import verify_email
    v = verify_email(email)
    if not v["valid_syntax"] or v["is_disposable"]:
        return "drop"
    if v["is_freemail"]:
        return "owner"                       # freemail on a business site = the owner-operator
    if email.split("@")[-1].endswith(domain):
        return "role" if v["is_role"] else "person"
    return "other"


def _whois_registrant(domain: str) -> dict:
    """Registrant email/phone/name from WHOIS, with privacy-proxy records dropped (their
    phone is the proxy's, not the owner's). Real for small biz that never enabled privacy."""
    import subprocess
    try:
        out = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return {}
    proxy = ("domains by proxy", "registration private", "privacy", "redacted", "whoisguard",
             "withheld", "/whois", "contactdomainowner", "not disclosed", "perfect privacy")
    got = {}
    for line in out.splitlines():
        m = re.match(r"\s*Registrant (Email|Phone|Name|Organization)\s*:\s*(.+)", line, re.I)
        if m and m.group(1).lower() not in got:
            got[m.group(1).lower()] = m.group(2).strip()
    if any(p in str(v).lower() for v in got.values() for p in proxy):
        return {}
    return {k: v for k, v in got.items() if v}


def find_contact(website: str, workers: int = 4) -> dict:
    """Dig a business's public owner contact: crawl its key sections, extract + rank emails
    (owner freemail first), tel: phones, socials, and WHOIS registrant. All public data."""
    ex = Extractor()
    try:
        targets = crawl_site(website, limit=8)
    except Exception:
        targets = [(None, website)]          # crawl failed → still try the homepage
    out = ex.extract([u for _, u in targets], concurrency=workers)
    emails, phones, socials = set(), set(), set()
    for r in out.results:
        emails |= set(r.emails)
        phones |= set(r.phones)
        socials |= set(r.socials)
    domain = _registrable(website)
    classified = [(_email_type(e, domain), e) for e in emails]
    ranked = sorted(((t, e) for t, e in classified if t != "drop"),
                    key=lambda te: (_EMAIL_RANK.get(te[0], 9), te[1]))
    return {"website": website, "domain": domain, "pages": len(out.results),
            "emails": [{"email": e, "type": t} for t, e in ranked],
            "phones": sorted(phones), "socials": sorted(socials),
            "whois": _whois_registrant(domain)}


def render_contact(c: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(c, indent=2)
    out = [f"CONTACT: {c['domain']}  ({c['pages']} pages crawled)", "emails:"]
    out += [f"  {e['email']:34} [{e['type']}]" for e in c["emails"]] or ["  (none found)"]
    out.append(f"phones:  {', '.join(c['phones']) or '(none published)'}")
    out.append(f"socials: {', '.join(c['socials'][:6]) or '(none)'}")
    out.append(f"whois:   {c['whois'] or '(private / proxied)'}")
    return "\n".join(out)


# directories/aggregators/social — not the business's own site; skip when prospecting.
_AGGREGATORS = ("yelp.", "facebook.", "angi.", "angieslist.", "bbb.org", "yellowpages.",
                "google.", "indeed.", "reddit.", "thumbtack.", "mapquest.", "linkedin.",
                "instagram.", "houzz.", "nextdoor.", "glassdoor.", "tripadvisor.", "amazon.",
                "wikipedia.", "youtube.", "pinterest.", "manta.", "chamberofcommerce.")


def _business_urls(results, limit):
    """From search results, keep one URL per real business domain (drop aggregators/dirs)."""
    from urllib.parse import urlsplit
    urls, seen = [], set()
    for r in results:
        u = (r.get("url") or "").strip()
        dom = urlsplit(u).netloc.lower()
        if not dom or dom in seen or any(a in dom for a in _AGGREGATORS):
            continue
        seen.add(dom)
        urls.append(u)
        if len(urls) >= limit:
            break
    return urls


def searx_urls(query, limit=10):
    """Search a SearXNG instance -> business homepage URLs. Instance from $PITH_SEARX_URL."""
    import os
    from urllib.parse import urlencode
    base = os.environ.get("PITH_SEARX_URL")
    if not base:
        raise SystemExit("--prospect needs a SearXNG instance: set PITH_SEARX_URL=http://host:port")
    url = base.rstrip("/") + "/search?" + urlencode({"q": query, "format": "json"})
    data = json.load(urllib.request.urlopen(url, timeout=25))
    return _business_urls(data.get("results", []), limit)


def prospect(query, limit=10, workers=4):
    """One category+geo search -> a lead list, each with dug owner contact. The GTM top of funnel."""
    leads = []
    for url in searx_urls(query, limit):
        print(f"[prospect] {url}", file=sys.stderr, flush=True)
        leads.append(find_contact(url, workers=workers))
    return leads


def _best_contact(lead):
    if lead["emails"]:
        return lead["emails"][0]["email"], lead["emails"][0]["type"]
    if lead["phones"]:
        return lead["phones"][0], "phone"
    return "-", "-"


def render_leads(leads, fmt):
    if fmt == "json":
        return json.dumps(leads, indent=2)
    if fmt == "csv":
        import csv as _csv
        import io
        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["business", "best_contact", "contact_type", "phone", "socials"])
        for l in leads:
            best, typ = _best_contact(l)
            w.writerow([l["domain"], best, typ, (l["phones"][0] if l["phones"] else ""), ";".join(l["socials"][:3])])
        return buf.getvalue().rstrip()
    out = [f"{'business':30} {'best contact':34} {'type':8} phone"]
    for l in leads:
        best, typ = _best_contact(l)
        out.append(f"{l['domain'][:30]:30} {best[:34]:34} {typ:8} {l['phones'][0] if l['phones'] else '-'}")
    out.append(f"\n{len(leads)} leads · {sum(1 for l in leads if l['emails'] or l['phones'])} with contact")
    return "\n".join(out)


def render_enrich(rows, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2)
    if fmt == "csv":
        import csv as _csv
        import io
        cols = ["company", "website", "pages", "linkedin", "github", "twitter", "careers", "emails"]
        buf = io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "emails": ";".join(r["emails"])})
        return buf.getvalue().rstrip()
    # table
    out = [f"{'company':14} {'pg':>2} {'careers':7} {'linkedin':30} emails"]
    for r in rows:
        out.append(f"{r['company'][:14]:14} {r['pages']:>2} {'yes' if r['careers'] else '-':7} "
                   f"{(r['linkedin'] or '-')[:30]:30} {','.join(r['emails'])[:40]}")
    return "\n".join(out)


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


def run_batch(ex, targets, *, full, render_js, workers, verbose=False):
    """Drive the extractor over targets, one extract() per URL so we can show progress
    and parallelize. Returns (label, url, Result | error-dict) rows in input order."""
    total = len(targets)
    # tier-safety: a walled URL spawns a stealth browser (~hundreds of MB). If any target is
    # walled, cap concurrency so a big --workers can't OOM the box (browser knee is ~3 anyway,
    # measured in walled-physics.md). Pure open-web batches keep full --workers.
    if workers > _BROWSER_MAX_CONCURRENCY and any(_needs_browser(u) for _, u in targets):
        workers = _BROWSER_MAX_CONCURRENCY
    log.info("batch_start", extra={"n": total, "workers": workers})

    def one(item):
        i, (label, url) = item
        if verbose:
            log.info("fetch_start", extra={"i": i, "n": total, "url": url, "label": label})
        else:
            print(f"[{i}/{total}] {label or url}", file=sys.stderr, flush=True)
        out = ex.extract(urls=[url], full_content=full, render_js=render_js)
        return (label, url, out.results[0] if out.results else out.errors[0])

    items = list(enumerate(targets, 1))
    if workers > 1:
        # ponytail: thread the fetches; the stealth browser launches per-call so it's
        # thread-safe enough here. Drop --workers to 1 if a site gets flaky under load.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, items))
    else:
        rows = [one(it) for it in items]
    ok = sum(1 for _, _, r in rows if isinstance(r, Result))
    log.info("batch_done", extra={"n": total, "ok": ok, "errors": total - ok})
    return rows


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
    ap.add_argument("--from", dest="from_file", metavar="FILE", help="batch: read URLs from a list file (txt or csv)")
    ap.add_argument("--sitemap", metavar="URL", help="batch: crawl a sitemap.xml and gather every page (filter with --match)")
    ap.add_argument("--crawl", metavar="URL", help="batch: from a homepage, follow links into about/contact/team/... sections")
    ap.add_argument("--match", metavar="SUBSTR", help="with --sitemap: keep only URLs containing this substring")
    ap.add_argument("--limit", type=int, default=25, help="cap pages gathered by --sitemap/--crawl (default 25)")
    ap.add_argument("--prospect", metavar="QUERY", help="GTM: search a category+geo (needs $PITH_SEARX_URL) -> a lead list, each with dug owner contact")
    ap.add_argument("--find", metavar="URL", help="GTM: dig a business's public owner contact (ranked emails, phones, socials, WHOIS)")
    ap.add_argument("--enrich", metavar="FILE", help="GTM: read a company list (name,website csv) and output an enriched row per company (socials, emails, careers)")
    ap.add_argument("--about", metavar="QUERY", help="batch: rank candidates by relevance to this (e.g. a target name+company) and fetch the most relevant first")
    ap.add_argument("--budget", type=int, help="with --about: fetch only the top-N most relevant candidates (skip the rest — saves the 4-5s/page walled-fetch cost)")
    ap.add_argument("--format", choices=["md", "json", "table", "csv"], default="md", help="output format (csv/json for --enrich; default md)")
    ap.add_argument("--workers", type=int, default=1, help="batch: parallel fetches (default 1)")
    ap.add_argument("--full", action="store_true", help="include full page markdown")
    ap.add_argument("--js", action="store_true", help="force a real browser (JS-rendered / bot-protected pages)")
    ap.add_argument("--verbose", "-v", action="store_true", help="stream a structured NDJSON trace of every pipeline step (tiers, timing, concurrency, network) to stderr")
    args = ap.parse_args()

    if args.verbose:
        _enable_trace()
    render_js = True if args.js else "auto"
    ex = Extractor()

    if args.prospect:  # GTM: search a category+geo -> lead list with owner contact
        leads = prospect(args.prospect, limit=args.limit, workers=args.workers)
        print(render_leads(leads, "table" if args.format == "md" else args.format))
        return

    if args.find:  # GTM: dig one business's owner contact
        print(render_contact(find_contact(args.find, workers=args.workers),
                             "json" if args.format == "json" else "table"))
        return

    if args.enrich:  # GTM: company list -> enriched rows
        companies = read_targets(args.enrich)
        if not companies:
            ap.error(f"no companies found in {args.enrich}")
        rows = [enrich_company(name or url, url, workers=args.workers) for name, url in companies]
        print(render_enrich(rows, "table" if args.format == "md" else args.format))
        return

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
            log.info("gate_ranked", extra={"candidates": n, "kept": len(targets), "budget": args.budget, "query": args.about})
            if not args.verbose:
                print(f"gate: ranked {n} candidates by '{args.about}'"
                      + (f", fetching top {args.budget}" if args.budget else ""), file=sys.stderr)
        rows = run_batch(ex, targets, full=args.full,
                         render_js=render_js, workers=args.workers, verbose=args.verbose)
        print(render(rows, args.format))
        return

    if not args.url:
        ap.error("provide a URL, or --from FILE for a list")

    out = ex.extract(urls=[args.url], full_content=args.full, render_js=render_js)
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
