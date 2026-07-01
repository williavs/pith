"""Scout — a solo-dev prospecting console over pith, built to SHOW pith off: pick a
cold-call-friendly area + a trade bundle; pith sweeps YellowPages+SuperPages across many
categories, grades every site's modernness CONCURRENTLY (its tiered fetch), digs each
owner's contact + socials, and streams a live funnel (+ throughput number) to the browser.
Output: a ranked set of "opportunities" (dated-site small businesses with owner contact +
RRM-style conversation starters) ready to feed an LLM for pitch synthesis.

Backend is stdlib only (http.server) — runs with just `pip install pith[js]`. Real pith,
no mocks. Run:  python examples/scout/server.py  then open http://localhost:8848
"""
import json
import logging
import queue
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.cli import directory_search, contact_evidence, _registrable, _domain_age_years
from pith.core import _fetch_static
from pith.techstack import analyze
from pith.resolve import resolve_person, Target
from pith import recipes

HERE = Path(__file__).resolve().parent

# mid-market, owner-operated-dense regions where cold-calling small biz still lands (and
# agencies haven't saturated). These are the opinionated starting set the operator picks from.
AREAS = [
    "Columbus, OH", "Cincinnati, OH", "Indianapolis, IN", "Fort Wayne, IN", "Grand Rapids, MI",
    "Kansas City, MO", "Omaha, NE", "Des Moines, IA", "Wichita, KS", "Tulsa, OK",
    "Chattanooga, TN", "Greenville, SC", "Spokane, WA", "Boise, ID", "Fort Worth, TX",
]

# a bundle = many categories swept as one "opportunity type". Small local trades are where
# dated sites (and reachable owner-operators) cluster. Type a bundle key OR a raw category.
BUNDLES = {
    "trades":  ["plumbers", "hvac", "roofing", "electricians", "landscaping",
                "garage door repair", "fencing contractors", "pest control"],
    "auto":    ["auto repair", "transmission repair", "auto body shop", "tire shop", "towing"],
    "local":   ["florist", "jewelry store", "furniture store", "appliance repair",
                "dry cleaners", "nail salon"],
    "food":    ["restaurants", "catering", "bakery", "coffee shop"],
    "health":  ["chiropractor", "dentist", "veterinarian", "physical therapy", "optometrist"],
    "pro":     ["accountant", "law firm", "insurance agency", "real estate agent", "tax preparation"],
}

_GRADE_RANK = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "?": 5}
GRADE_WORKERS = 16          # flat curl_cffi fetches; stable to ~20. I/O-bound, absorbs slow-host tail
DIG_WORKERS = 6             # contact_evidence nests its own Extractor pool — keep OUTER×INNER bounded (see _dig)
DIG_INNER = 2               # Extractor concurrency inside each contact_evidence; 6×2=12 total native fetches (safe)
PER_CAT = 18                # ~1 directory page/source per category — fast, still ~120 businesses across a bundle

# per-category "platform play" for the MULTIPLY starter (HFL's real pitch: not a $2k site)
_PLAYS = {
    "plumbers": "online booking + dispatch scheduling", "hvac": "maintenance-plan portal + seasonal booking",
    "roofing": "instant-quote form + job-photo gallery", "electricians": "quote intake + scheduling",
    "landscaping": "seasonal-service scheduling + quote form", "restaurants": "online ordering + reservations",
    "dentist": "appointment booking + patient intake", "chiropractor": "online scheduling + intake forms",
    "law firm": "intake automation + client portal", "real estate agent": "IDX listing site + lead capture",
    "auto repair": "online appointment booking + service reminders",
}


# ---- live observability: stream pith's own internal trace into the SSE log ----------------
def _short_url(u: str) -> str:
    try:
        p = urlparse(u or "")
        path = p.path if p.path and p.path != "/" else ""
        return (p.netloc + path)[:46]
    except Exception:
        return (u or "")[:46]


def _kb(n) -> str:
    return f"{round((n or 0) / 1024)}KB" if n else "?"


def _drain(q: "queue.Queue"):
    """Yield everything queued so far (pith trace records pushed from worker threads)."""
    try:
        while True:
            yield q.get_nowait()
    except queue.Empty:
        pass


class _SSEHandler(logging.Handler):
    """Turns pith's structured log records (tier / tier_fail, emitted per page fetch inside
    the Extractor) into readable SSE log lines. Thread-safe via a queue the generator drains."""
    def __init__(self, q: "queue.Queue"):
        super().__init__(level=logging.DEBUG)
        self.q = q

    def emit(self, r: logging.LogRecord):
        try:
            ev, d = r.getMessage(), r.__dict__
            if ev == "tier":
                self.q.put(("log", {"kind": "tier",
                    "msg": f"      → {_short_url(d.get('url'))}  [{d.get('tier')} {d.get('ms')}ms {_kb(d.get('bytes'))}]"}))
            elif ev == "tier_fail":
                self.q.put(("log", {"kind": "tierfail",
                    "msg": f"      → {_short_url(d.get('url'))}  [{d.get('tier')} failed: {str(d.get('err',''))[:38]}]"}))
        except Exception:
            pass


def expand(category: str) -> list[str]:
    """A bundle key -> its categories; anything else -> itself (raw category)."""
    return BUNDLES.get(category.lower().strip(), [category])


def _safe_dir(cat: str, area: str) -> list[dict]:
    try:
        rows = directory_search(cat, area, limit=PER_CAT)
    except Exception:
        return []
    for r in rows:
        r["category"] = cat
    return rows


def gather_businesses(cats: list[str], area: str) -> list[dict]:
    """Sweep every category concurrently, then dedup by registrable domain (a business listed
    under plumbers AND hvac, or on both YP and SuperPages, collapses to one)."""
    out = []
    with ThreadPoolExecutor(max_workers=4) as pool:      # modest: don't trip YP rate-limits
        for rows in pool.map(lambda c: _safe_dir(c, area), cats):
            out.extend(rows)
    seen, deduped = set(), []
    for b in out:
        dom = _registrable(b["website"]) if b.get("website") else ""
        key = dom or (b["name"].lower(), re.sub(r"\D", "", b.get("phone", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(b)
    return deduped


GRADE_TIMEOUT = 8       # a dead/slow small-biz host must not hold a worker for the full 30s default

def _grade(b: dict):
    """Business -> (business, intel) or None. Fast-fetch (8s cap) + tech analysis only; WHOIS
    domain-age is deferred to the dig phase so it runs for ~18 survivors, not all 31 sites."""
    url = b["website"]
    html, tier = "", None
    try:
        from curl_cffi import requests as creq
        html = creq.get(url, impersonate="chrome", timeout=GRADE_TIMEOUT).text
        tier = "impersonate"
    except Exception:
        try:
            html = _fetch_static(url)          # fallback if curl_cffi/impersonate unavailable
            tier = "static"
        except Exception:
            return None
    if not html:
        return None
    intel = analyze(html, url)
    intel["grade"] = intel.get("modernness_grade")
    intel["_tier"], intel["_bytes"] = tier, len(html)
    return b, intel


def _owner_shape(ev: dict) -> dict:
    """Collapse a pith contact_evidence result (Fact objects + Coverage) back into the flat
    'owner' shape the frontend SSE contract expects. pith no longer picks a 'primary' — the
    recipes apply Scout's judgment (owner-preferred email, corroboration-ranked phones)."""
    facts = ev["facts"]
    email_facts = [f for f in facts if f.kind == "email"]
    phone_facts = recipes.rank_phones(facts)                          # ranked by corroboration
    social_facts = [f for f in facts if f.kind == "social"]
    name_facts = [f for f in facts if f.kind == "name"]
    return {
        "emails": [{"email": f.value, "type": f.labels.get("email_type")}
                   for f in email_facts if f.labels.get("email_type")],
        "phones": [{"number": f.value, "sources": f.corroboration} for f in phone_facts],
        "socials": [f.value for f in social_facts],
        "people": [{"name": f.value, "title": f.labels.get("title", "")} for f in name_facts],
        "pages": len(ev["coverage"].ok),                              # crawled-OK page count (for the log line)
    }


def _dig(b: dict, intel: dict):
    """Worker-thread dig: owner contact + WHOIS domain-age together, so both run concurrently
    across the pool (NOT serialized in the SSE yield loop)."""
    try:
        ev = contact_evidence(b["website"], workers=DIG_INNER)   # bound nested concurrency (native fetch libs)
    except Exception:
        return None
    contact = _owner_shape(ev)
    intel = {**intel, "domain_age_years": _domain_age_years(_registrable(b["website"]))}
    return b, intel, contact


def conversation_starters(biz, intel, contact):
    """RRM-flavored hooks (Ruin=the pain, Route=the way in, Multiply=the platform play),
    keyed to THIS site's real signals and rotated by domain so no two cards read the same."""
    seed = sum(ord(c) for c in biz.get("website", "x"))
    pick = lambda v: v[seed % len(v)]
    cat = biz.get("category", "local")
    s = []
    if not intel.get("responsive"):
        s.append(pick([
            "RUIN: not mobile-responsive — every phone search bounces. ~60% of local traffic is mobile.",
            "RUIN: site breaks on phones — invisible to the mobile searchers who'd actually call.",
            "RUIN: no responsive layout — Google demotes it on mobile, where their customers search.",
        ]))
    dated = intel.get("dated_signals") or []
    if dated:
        s.append(pick([
            f"RUIN: dated stack ({', '.join(dated[:2])}) — grades {intel['grade']}, reads 'abandoned' to a buyer.",
            f"RUIN: {', '.join(dated[:2])} under the hood — a {intel['grade']}-grade site that looks closed.",
        ]))
    if intel.get("hosted_builder"):
        s.append(pick([
            f"RUIN: it's a {intel['builder']} template — paying monthly to look like everyone else.",
            f"RUIN: locked into {intel['builder']} — recurring fee, generic template, zero ownership.",
        ]))
    if intel.get("domain_age_years"):
        s.append(pick([
            f"CONTEXT: {intel['domain_age_years']} yrs online — real business, neglected web presence.",
            f"CONTEXT: domain's {intel['domain_age_years']} yrs old — established, just never updated the site.",
        ]))
    people = contact.get("people") or []
    if people:
        p = people[0]
        s.append(f"ROUTE: reach {p['name']}" + (f" ({p['title']})" if p.get("title") else "") + " directly.")
    elif contact.get("emails"):
        e = contact["emails"][0]
        s.append(pick([
            f"ROUTE: {'owner-operator' if e['type'] == 'owner' else e['type']} inbox {e['email']} — small shop, they read it.",
            f"ROUTE: {e['email']} ({e['type']}) — one hop to the decision-maker at a shop this size.",
        ]))
    elif contact.get("phones"):
        ph = contact["phones"][0]
        s.append(f"ROUTE: call {ph['number']} ({ph['sources']} sources) — owner-operator likely answers.")
    play = _PLAYS.get(cat, "booking / CRM / lead-capture")
    s.append(pick([
        f"MULTIPLY: not a $2k rebuild — a {cat} this size needs {play}. That's the platform play.",
        f"MULTIPLY: the deal isn't the website, it's {play} on top — recurring value, not a one-off.",
    ]))
    return s


def _opportunity_score(intel, contact):
    """Lower grade + older + reachable owner = hotter. Higher score first."""
    g = 5 - _GRADE_RANK.get(intel.get("grade", "?"), 5)     # F=5 ... A=1
    reach = 3 if any(e["type"] == "owner" for e in contact["emails"]) else (2 if contact["emails"] else 0)
    reach += 2 if contact["phones"] else 0
    reach += 1 if contact.get("socials") else 0
    age = min(3, (intel.get("domain_age_years") or 0) // 5)
    return g * 3 + reach + age


def build_opportunity(biz, intel, contact):
    return {
        "name": biz["name"], "website": biz["website"], "address": biz.get("address", ""),
        "category": biz.get("category", ""),
        "grade": intel.get("grade"), "builder": intel.get("builder"),
        "hosted_builder": intel.get("hosted_builder"), "responsive": intel.get("responsive"),
        "domain_age_years": intel.get("domain_age_years"),
        "owner": {
            "people": contact.get("people", []),
            "emails": contact["emails"],
            "phones": contact["phones"],               # [{number, sources}] — waterfall confidence
            "socials": contact["socials"],
        },
        "conversation_starters": conversation_starters(biz, intel, contact),
        "score": _opportunity_score(intel, contact),
    }


def scout_events(category, area, limit):
    """Generator of (event, data) for SSE. Streams the observability funnel + the results.
    Grade and dig run CONCURRENTLY (pith's tiered fetch) — the throughput number is the point."""
    t0 = time.time()
    cats = expand(category)
    yield "log", {"msg": f"pith sweep: {len(cats)} categor{'ies' if len(cats) > 1 else 'y'} × {area}  [{', '.join(cats)}]"}
    businesses = gather_businesses(cats, area)
    sites = [b for b in businesses if b.get("website")]
    yield "stats", {"scanned": len(businesses), "with_site": len(sites), "dated": 0, "opportunities": 0}
    yield "log", {"msg": f"directory: {len(businesses)} businesses ({len(sites)} with sites), deduped, in {time.time() - t0:.1f}s"}

    if not sites:
        yield "done", {"count": 0, "elapsed": round(time.time() - t0, 1), "scanned": len(businesses), "graded": 0, "throughput": 0}
        return

    q = queue.Queue()                                  # pith trace records land here (worker threads)
    lg = logging.getLogger("pith")
    handler = _SSEHandler(q)
    prev_level = lg.level
    lg.setLevel(logging.DEBUG)
    lg.addHandler(handler)
    rate = 0
    try:
        # ---- grade: concurrent, richer per-site line ----
        yield "log", {"msg": f"grading {len(sites)} sites concurrently ({GRADE_WORKERS}× pith tiered fetch)…", "kind": "phase"}
        tg = time.time()
        kept, graded = [], 0
        with ThreadPoolExecutor(max_workers=GRADE_WORKERS) as pool:
            futs = {pool.submit(_grade, b): b for b in sites}
            pending = set(futs)
            while pending:
                yield from _drain(q)
                for f in [x for x in pending if x.done()]:
                    pending.discard(f)
                    graded += 1
                    res = f.result()
                    if res is None:
                        continue
                    b, intel = res
                    g = intel["grade"]
                    ds = intel.get("dated_signals") or []
                    line = (f"  [{graded}/{len(sites)}] {b['name'][:30]}: {g} · {intel.get('builder')} · "
                            f"resp:{'Y' if intel.get('responsive') else 'N'} https:{'Y' if intel.get('https') else 'N'} "
                            f"[{intel.get('_tier')} {_kb(intel.get('_bytes'))}]")
                    if ds:
                        line += f" · dated:{','.join(ds[:3])}"
                    yield "log", {"msg": line, "kind": "grade"}
                    if _GRADE_RANK.get(g, 5) <= _GRADE_RANK["C"]:
                        kept.append((b, intel))
                if pending:
                    try:
                        yield q.get(timeout=0.15)      # block briefly so trace streams live
                    except queue.Empty:
                        pass
        yield from _drain(q)
        dt = time.time() - tg
        rate = len(sites) / dt if dt > 0 else 0
        yield "stats", {"scanned": len(businesses), "with_site": len(sites), "dated": len(kept), "opportunities": 0}
        yield "log", {"msg": f"graded {len(sites)} sites in {dt:.1f}s ({rate:.1f}/s) — {len(kept)} dated (C/D/F)", "kind": "stat"}

        kept.sort(key=lambda bi: _GRADE_RANK.get(bi[1]["grade"], 5))    # worst sites (best leads) first
        kept = kept[:limit]

        # ---- dig: concurrent; pith's per-page fetch trace streams under each site ----
        yield "log", {"msg": f"digging owner contact for {len(kept)} targets concurrently ({DIG_WORKERS}×) — crawling each site's key pages…", "kind": "phase"}
        found = 0
        with ThreadPoolExecutor(max_workers=DIG_WORKERS) as pool:
            futs = [pool.submit(_dig, b, intel) for b, intel in kept]
            pending = set(futs)
            while pending:
                yield from _drain(q)
                for f in [x for x in pending if x.done()]:
                    pending.discard(f)
                    res = f.result()
                    if res is None:
                        continue
                    b, intel, contact = res
                    opp = build_opportunity(b, intel, contact)
                    found += 1
                    yield "opportunity", opp
                    yield "stats", {"scanned": len(businesses), "with_site": len(sites), "dated": len(kept), "opportunities": found}
                    owner = "owner-operator" if any(e["type"] == "owner" for e in contact["emails"]) else "no owner email"
                    yield "log", {"kind": "hit", "msg":
                        (f"  #{found} {b['name'][:26]}: crawled {contact['pages']}pg → "
                         f"{len(contact['emails'])} email, {len(contact['phones'])} phone, "
                         f"{len(contact['socials'])} social, {len(contact.get('people', []))} person · "
                         f"{owner} · {intel.get('domain_age_years') or '?'}yr · score {opp['score']}")}
                if pending:
                    try:
                        yield q.get(timeout=0.15)
                    except queue.Empty:
                        pass
        yield from _drain(q)
    finally:
        lg.removeHandler(handler)
        lg.setLevel(prev_level)

    total = time.time() - t0
    yield "done", {"count": found, "elapsed": round(total, 1), "scanned": len(businesses),
                   "graded": len(sites), "throughput": round(rate, 1)}


def deep_events(website):
    """On-demand deep profile scan for one opportunity's owner: enumerate + cross-corroborate
    their public profiles -> where they're most active + confidence."""
    yield "log", {"msg": f"deep scan: {website}"}
    contact = _owner_shape(contact_evidence(website))
    domain = _registrable(website)
    handle = None
    for s in contact["socials"]:
        seg = s.rstrip("/").rsplit("/", 1)[-1]
        if seg and seg not in ("sharer.php", "tr"):
            handle = seg
            break
    if not handle and contact["emails"]:
        handle = contact["emails"][0]["email"].split("@")[0]
    if not handle:
        yield "done", {"person": None, "msg": "no handle to enumerate"}
        return
    yield "log", {"msg": f"enumerating + verifying profiles for handle '{handle}' vs {domain}"}
    name = contact["people"][0]["name"] if contact["people"] else ""
    person = resolve_person(handle, Target(name=name, website=website), all_sites=True)
    yield "log", {"msg": f"verified {len(person['profiles'])} profiles · confidence {person['confidence']}"}
    yield "done", {"person": person}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body if isinstance(body, bytes) else body.encode())

    def _sse(self, gen):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for event, data in gen:
                self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, "text/html", (HERE / "index.html").read_text())
        elif u.path == "/areas":
            self._send(200, "application/json", json.dumps({"areas": AREAS, "bundles": list(BUNDLES)}))
        elif u.path == "/scout":
            self._sse(scout_events(q.get("category", ["trades"])[0], q.get("area", ["Columbus, OH"])[0],
                                   int(q.get("limit", ["25"])[0])))
        elif u.path == "/deep":
            self._sse(deep_events(q.get("website", [""])[0]))
        else:
            self._send(404, "text/plain", "not found")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8848
    print(f"Scout console → http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
