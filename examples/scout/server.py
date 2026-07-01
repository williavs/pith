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
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.cli import directory_search, find_contact, _registrable, _domain_age_years
from pith.core import _fetch_static
from pith.techstack import analyze
from pith.resolve import resolve_person, Target

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
GRADE_WORKERS = 20          # I/O-bound + slow dated hosts hold a worker on the full timeout; more absorbs the tail
DIG_WORKERS = 12            # find_contact crawls multiple pages per site (heavier); dig every survivor at once
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
    html = ""
    try:
        from curl_cffi import requests as creq
        html = creq.get(url, impersonate="chrome", timeout=GRADE_TIMEOUT).text
    except Exception:
        try:
            html = _fetch_static(url)          # fallback if curl_cffi/impersonate unavailable
        except Exception:
            return None
    if not html:
        return None
    intel = analyze(html, url)
    intel["grade"] = intel.get("modernness_grade")
    return b, intel


def _dig(b: dict, intel: dict):
    """Worker-thread dig: owner contact + WHOIS domain-age together, so both run concurrently
    across the pool (NOT serialized in the SSE yield loop)."""
    try:
        contact = find_contact(b["website"])
    except Exception:
        return None
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

    yield "log", {"msg": f"grading {len(sites)} sites concurrently ({GRADE_WORKERS}× pith tiered fetch)…"}
    tg = time.time()
    kept, graded = [], 0
    with ThreadPoolExecutor(max_workers=GRADE_WORKERS) as pool:
        futs = {pool.submit(_grade, b): b for b in sites}
        for fut in as_completed(futs):
            graded += 1
            res = fut.result()
            if res is None:
                continue
            b, intel = res
            g = intel["grade"]
            yield "log", {"msg": f"  [{graded}/{len(sites)}] {b['name'][:34]}: {g} · {intel.get('builder')}"}
            if _GRADE_RANK.get(g, 5) <= _GRADE_RANK["C"]:
                kept.append((b, intel))
    dt = time.time() - tg
    rate = len(sites) / dt if dt > 0 else 0
    yield "stats", {"scanned": len(businesses), "with_site": len(sites), "dated": len(kept), "opportunities": 0}
    yield "log", {"msg": f"⚡ graded {len(sites)} sites in {dt:.1f}s ({rate:.1f}/s) — {len(kept)} dated (C/D/F)"}

    kept.sort(key=lambda bi: _GRADE_RANK.get(bi[1]["grade"], 5))    # worst sites (best leads) first
    kept = kept[:limit]
    yield "log", {"msg": f"digging owner contact for {len(kept)} targets concurrently ({DIG_WORKERS}×)…"}
    found = 0
    with ThreadPoolExecutor(max_workers=DIG_WORKERS) as pool:
        futs = [pool.submit(_dig, b, intel) for b, intel in kept]
        for fut in as_completed(futs):
            res = fut.result()
            if res is None:
                continue
            b, intel, contact = res
            opp = build_opportunity(b, intel, contact)
            found += 1
            yield "opportunity", opp
            yield "stats", {"scanned": len(businesses), "with_site": len(sites), "dated": len(kept), "opportunities": found}
            yield "log", {"msg": f"  ★ #{found} {b['name'][:30]} (grade {intel['grade']}, score {opp['score']})"}
    total = time.time() - t0
    yield "done", {"count": found, "elapsed": round(total, 1), "scanned": len(businesses),
                   "graded": len(sites), "throughput": round(rate, 1)}


def deep_events(website):
    """On-demand deep profile scan for one opportunity's owner: enumerate + cross-corroborate
    their public profiles -> where they're most active + confidence."""
    yield "log", {"msg": f"deep scan: {website}"}
    contact = find_contact(website)
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
