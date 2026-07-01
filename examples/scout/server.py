"""Scout — a solo-dev prospecting console over pith. Pick a cold-call-friendly area + a
business category; pith builds a list, grades each site's modernness, digs the owner's
contact + socials, and streams every step to the browser (SSE observability). Output is a
set of "opportunities" (outdated-site small businesses with owner contact + RRM-style
conversation starters) ready to feed an LLM for ICP/pitch synthesis.

Backend is stdlib only (http.server) — runs with just `pip install pith[js]`. Real pith,
no mocks. Run:  python examples/scout/server.py  then open http://localhost:8848
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.cli import directory_search, website_intel, find_contact, _registrable
from pith.resolve import resolve_person, Target

HERE = Path(__file__).resolve().parent

# mid-market, owner-operated-dense regions where cold-calling small biz still lands (and
# agencies haven't saturated). A fuller version would RANK areas by outdated-site density;
# these are the opinionated starting set the operator picks from.
AREAS = [
    "Columbus, OH", "Cincinnati, OH", "Indianapolis, IN", "Fort Wayne, IN", "Grand Rapids, MI",
    "Kansas City, MO", "Omaha, NE", "Des Moines, IA", "Wichita, KS", "Tulsa, OK",
    "Chattanooga, TN", "Greenville, SC", "Spokane, WA", "Boise, ID", "Fort Worth, TX",
]

_GRADE_RANK = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "?": 5}


def conversation_starters(biz, intel, contact):
    """Deterministic RRM-flavored hooks (Ruin = the pain, Route = the way in, Multiply = the
    bigger platform play). These feed the operator's LLM for the actual pitch."""
    s = []
    if not intel.get("responsive"):
        s.append("RUIN: site isn't mobile-responsive — they're losing every phone visitor (most local searches).")
    if intel.get("hosted_builder"):
        s.append(f"RUIN: it's a {intel['builder']} template — generic, and they're paying monthly for it.")
    elif intel.get("grade") in ("D", "F"):
        s.append(f"RUIN: site grades {intel['grade']} — dated tech ({', '.join(intel.get('dated_signals', [])) or 'old stack'}).")
    if intel.get("domain_age_years"):
        s.append(f"CONTEXT: online {intel['domain_age_years']} yrs — established, just neglected online.")
    owner = contact.get("people") or []
    if owner:
        s.append(f"ROUTE: reach {owner[0]['name']}" + (f" ({owner[0]['title']})" if owner[0].get('title') else "") + " directly.")
    elif contact["emails"]:
        e = contact["emails"][0]
        s.append(f"ROUTE: {'owner-operator' if e['type'] == 'owner' else e['type']} email {e['email']}.")
    s.append(f"MULTIPLY: not just a rebuild — a {biz.get('category', 'local')} business this size usually needs booking/CRM/scheduling too. That's the platform play, not a $2k website.")
    return s


def _opportunity_score(intel, contact):
    """Lower grade + older + reachable owner = hotter. Higher score first."""
    g = 5 - _GRADE_RANK.get(intel.get("grade", "?"), 5)     # F=5 ... A=1
    reach = 3 if any(e["type"] == "owner" for e in contact["emails"]) else (2 if contact["emails"] else 0)
    reach += 2 if contact["phones"] else 0
    age = min(3, (intel.get("domain_age_years") or 0) // 5)
    return g * 3 + reach + age


def build_opportunity(biz, intel, contact):
    return {
        "name": biz["name"], "website": biz["website"], "address": biz.get("address", ""),
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
    """Generator of (event, data) for SSE. The observability stream + the results."""
    yield "log", {"msg": f"directory: YellowPages+SuperPages for '{category}' in {area}"}
    businesses = directory_search(category, area, limit=limit * 3)
    yield "log", {"msg": f"directory: {len(businesses)} businesses found"}
    found = []
    for biz in businesses:
        if not biz.get("website"):
            yield "log", {"msg": f"skip {biz['name']}: no website"}
            continue
        yield "log", {"msg": f"grading {biz['name']} ({biz['website']})"}
        try:
            intel = website_intel(biz["website"])
        except Exception as e:
            yield "log", {"msg": f"skip {biz['name']}: {str(e)[:40]}"}
            continue
        yield "log", {"msg": f"  grade {intel.get('grade')} · {intel.get('builder')} · resp={intel.get('responsive')}"}
        if _GRADE_RANK.get(intel.get("grade", "?"), 5) > _GRADE_RANK["C"]:
            yield "log", {"msg": f"  drop {biz['name']}: too modern (grade {intel.get('grade')})"}
            continue
        yield "log", {"msg": f"  digging owner contact for {biz['name']}"}
        contact = find_contact(biz["website"])
        opp = build_opportunity(biz, intel, contact)
        found.append(opp)
        yield "opportunity", opp
        yield "log", {"msg": f"  OPPORTUNITY #{len(found)}: {biz['name']} (grade {intel.get('grade')}, score {opp['score']})"}
        if len(found) >= limit:
            break
    yield "done", {"count": len(found)}


def deep_events(website):
    """On-demand deep profile scan for one opportunity's owner: enumerate + cross-corroborate
    their public profiles -> where they're most active + confidence."""
    yield "log", {"msg": f"deep scan: {website}"}
    contact = find_contact(website)
    domain = _registrable(website)
    # derive a candidate handle from a social or an email local-part
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
            self._send(200, "application/json", json.dumps(AREAS))
        elif u.path == "/scout":
            self._sse(scout_events(q.get("category", ["hvac"])[0], q.get("area", ["Columbus, OH"])[0],
                                   int(q.get("limit", ["25"])[0])))
        elif u.path == "/deep":
            self._sse(deep_events(q.get("website", [""])[0]))
        else:
            self._send(404, "text/plain", "not found")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8848
    print(f"Scout console → http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
