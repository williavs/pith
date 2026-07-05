"""pith as an HTTP API — POST JSON, get pith's deterministic extraction back, from ANY
language. Stdlib only (http.server); no framework, no API key. Run:

    python -m pith.serve [port]        # default 8900

    curl -s localhost:8900/health
    curl -s localhost:8900/extract      -d '{"urls":["https://example.com"]}'
    curl -s localhost:8900/intel        -d '{"url":"https://example.com"}'
    curl -s localhost:8900/contact      -d '{"website":"https://example.com"}'
    curl -s localhost:8900/directory    -d '{"category":"plumbers","location":"Tulsa, OK","limit":10}'
    curl -s localhost:8900/profiles     -d '{"handle":"torvalds"}'
    curl -s localhost:8900/verify-email -d '{"email":"jane@acme.com"}'

Every response is JSON and carries `_ms` (server-side wall time). Heavy (fetching) endpoints
pass through a global semaphore so a load test applies BACKPRESSURE instead of exhausting RAM
or aborting the native fetch libs under nested concurrency. Tune with PITH_MAX_CONCURRENCY
(default 16).
"""
import json
import os
import sys
import threading
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import Extractor, __version__, verify_email
from .core import UnsafeURL

_MAX = int(os.environ.get("PITH_MAX_CONCURRENCY", "16"))
_HEAVY = threading.Semaphore(_MAX)


MAX_URLS = int(os.environ.get("PITH_MAX_URLS", "200"))


class BadRequest(ValueError):
    """Client input was malformed — surfaces as HTTP 400, not 500."""


def _str(body, key):
    """Required non-empty string field, or a clean 400."""
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise BadRequest(f"'{key}' must be a non-empty string")
    return v.strip()


def _int(body, key, default, lo=1, hi=64):
    """Optional int field, clamped, or a clean 400 on non-numeric input."""
    v = body.get(key, default)
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be an integer, got {v!r}")
    return max(lo, min(hi, n))


def _opt_int(body, key):
    """Optional int field; absent/None -> None (no clamp). Bad value -> 400."""
    v = body.get(key)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be an integer, got {v!r}")


def _extract(body):
    urls = body.get("urls")
    if urls is None and body.get("url") is not None:
        urls = [_str(body, "url")]
    if not isinstance(urls, list):
        raise BadRequest("provide 'urls' (a list of URL strings) or 'url' (a string)")
    urls = [u for u in urls if isinstance(u, str) and u.strip()]
    if not urls:
        raise BadRequest("no valid URL strings in 'urls'")
    if len(urls) > MAX_URLS:
        raise BadRequest(f"too many urls: {len(urls)} (max {MAX_URLS} per request)")
    out = Extractor().extract(urls, render_js=body.get("js", "auto"),
                              concurrency=_int(body, "concurrency", min(8, len(urls))),
                              timeout=_opt_int(body, "timeout"))
    return {"results": [_result_json(r) for r in out.results],
            "errors": out.errors}   # errors are {url, error, reason} dicts — keep them joinable


def _result_json(r) -> dict:
    """Result -> JSON. asdict() skips @property, so add the Parallel-compat fields by hand."""
    d = asdict(r)
    d["excerpts"] = r.excerpts          # Parallel-compat: markdown as a one-element list
    d["full_content"] = r.full_content  # Parallel-compat: markdown under Parallel's field name
    return d


def _contact(body):
    from .cli import contact_evidence
    from .core import _guard_url
    ev = contact_evidence(_guard_url(_str(body, "website")), workers=_int(body, "workers", 4))
    return {"domain": ev["domain"], "facts": [f.as_dict() for f in ev["facts"]],
            "coverage": ev["coverage"].as_dict()}   # evidence, not a pick — apply pith.recipes on top


def _intel(body):
    from .cli import website_intel
    from .core import _guard_url
    return website_intel(_guard_url(_str(body, "url")))


def _directory(body):
    from .cli import directory_search
    rows = directory_search(_str(body, "category"), _str(body, "location"),
                            limit=_int(body, "limit", 30, lo=1, hi=500))
    return {"count": len(rows), "businesses": rows}


def _profiles(body):
    from .profiles import enumerate_profiles
    r = enumerate_profiles(_str(body, "handle"), persona=body.get("persona"),
                           all_sites=bool(body.get("all_sites")), sites=body.get("sites"),
                           report=True)   # surface coverage (what could NOT be checked)
    return {"count": len(r["profiles"]), "profiles": r["profiles"], "coverage": r["coverage"]}


def _verify(body):
    return verify_email(_str(body, "email"))


def _gravatar(body):
    from .gravatar import gravatar_profile
    return gravatar_profile(_str(body, "email"))


def _phone(body):
    from .phoneintel import phone_intel
    return phone_intel(_str(body, "number"), region=body.get("region"))


def _news(body):
    from .news import news_search
    items = news_search(_str(body, "company"), domain=body.get("domain"), qualifier=body.get("qualifier"),
                        window_days=_int(body, "window_days", 90, lo=1, hi=365))
    return {"count": len(items), "items": items}


def _jobs(body):
    from .jobs import jobs_search
    return jobs_search(_str(body, "company"), _str(body, "domain"))


def _financials(body):
    from .financials import company_intel
    return company_intel(_str(body, "company"), ticker=body.get("ticker"))


# path -> (handler, heavy?). heavy handlers do network fetches and go through the gate.
_ROUTES = {
    "/extract":      (_extract, True),
    "/contact":      (_contact, True),
    "/intel":        (_intel, True),
    "/directory":    (_directory, True),
    "/profiles":     (_profiles, True),
    "/verify-email": (_verify, False),
    "/gravatar":     (_gravatar, True),    # email -> public accounts pivot
    "/phone":        (_phone, False),      # offline phone intelligence
    "/news":         (_news, True),        # keyless buyer-intent news search
    "/jobs":         (_jobs, True),        # keyless job-board company intel
    "/financials":   (_financials, True),  # keyless SEC/funding/identity/market bundle (company_intel)
}


_CONSOLE = os.path.join(os.path.dirname(__file__), "console.html")
def _console_html() -> str:
    with open(_CONSOLE, encoding="utf-8") as f:   # single-file operator UI, served same-origin
        return f.read()


_READ_TIMEOUT = int(os.environ.get("PITH_READ_TIMEOUT", "15"))   # slowloris guard
_MAX_BODY = int(os.environ.get("PITH_MAX_BODY", str(4 * 1024 * 1024)))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive: connection reuse for load tests
    timeout = _READ_TIMEOUT                # socket read timeout — a stalled/slowloris client is dropped

    def log_message(self, *a):
        pass

    def _json(self, code, obj, t=None):
        if t is not None:
            obj.setdefault("_ms", round((time.time() - t) * 1000))
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"status": "ok", "service": "pith", "version": __version__, "max_concurrency": _MAX})
        elif path in ("/", "/console"):
            self._html(_console_html())
        else:
            self._json(404, {"error": "GET / (console) or /health; POST /extract /contact /intel /directory /profiles /verify-email /gravatar /phone /news /jobs /financials"})

    def _html(self, body: str):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        t = time.time()
        path = urlparse(self.path).path
        route = _ROUTES.get(path)
        if not route:
            return self._json(404, {"error": f"unknown endpoint {path}"}, t)
        handler, heavy = route
        try:
            n = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return self._json(400, {"error": "invalid Content-Length"}, t)
        if n > _MAX_BODY:
            return self._json(413, {"error": f"body too large ({n} bytes, max {_MAX_BODY})"}, t)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json(400, {"error": f"bad JSON body: {e}"}, t)
        if not isinstance(body, dict):
            return self._json(400, {"error": "JSON body must be an object"}, t)
        gate = _HEAVY if heavy else None
        if gate:
            gate.acquire()
        try:
            result = handler(body)
            result["_ms"] = round((time.time() - t) * 1000)
            self._json(200, result)
        except (BadRequest, UnsafeURL, ValueError) as e:   # ValueError = input validation (bad handle etc.)
            self._json(400, {"error": str(e)}, t)
        except Exception as e:
            self._json(500, {"error": str(e)[:200]}, t)
        finally:
            if gate:
                gate.release()


def serve(port=8900, host=None):
    # default loopback-only; set PITH_HOST (e.g. a Tailscale IP) to expose on the fleet.
    host = host or os.environ.get("PITH_HOST", "127.0.0.1")
    print(f"pith → http://{host}:{port}  (console at /)  ·  max_concurrency={_MAX}")
    print("  POST /extract /contact /intel /directory /profiles /verify-email /gravatar /phone /news /jobs /financials")
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8900)
