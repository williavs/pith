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

_MAX = int(os.environ.get("PITH_MAX_CONCURRENCY", "16"))
_HEAVY = threading.Semaphore(_MAX)


def _extract(body):
    urls = body.get("urls") or ([body["url"]] if body.get("url") else [])
    if not urls:
        raise ValueError("provide 'urls' (list) or 'url'")
    out = Extractor().extract(urls, full_content=bool(body.get("full_content")),
                              render_js=body.get("js", "auto"),
                              concurrency=int(body.get("concurrency", min(8, len(urls)))))
    return {"results": [asdict(r) for r in out.results], "errors": [str(e) for e in out.errors]}


def _contact(body):
    from .cli import find_contact
    return find_contact(body["website"], workers=int(body.get("workers", 4)))


def _intel(body):
    from .cli import website_intel
    return website_intel(body["url"])


def _directory(body):
    from .cli import directory_search
    rows = directory_search(body["category"], body["location"], limit=int(body.get("limit", 30)))
    return {"count": len(rows), "businesses": rows}


def _profiles(body):
    from .profiles import enumerate_profiles
    hits = enumerate_profiles(body["handle"], persona=body.get("persona"),
                              all_sites=bool(body.get("all_sites")), sites=body.get("sites"))
    return {"count": len(hits), "profiles": hits}


def _verify(body):
    return verify_email(body["email"])


# path -> (handler, heavy?). heavy handlers do network fetches and go through the gate.
_ROUTES = {
    "/extract":      (_extract, True),
    "/contact":      (_contact, True),
    "/intel":        (_intel, True),
    "/directory":    (_directory, True),
    "/profiles":     (_profiles, True),
    "/verify-email": (_verify, False),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # keep-alive: connection reuse for load tests

    def log_message(self, *a):
        pass

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._json(200, {"status": "ok", "service": "pith", "version": __version__, "max_concurrency": _MAX})
        else:
            self._json(404, {"error": "GET /health; POST /extract /contact /intel /directory /profiles /verify-email"})

    def do_POST(self):
        path = urlparse(self.path).path
        route = _ROUTES.get(path)
        if not route:
            return self._json(404, {"error": f"unknown endpoint {path}"})
        handler, heavy = route
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._json(400, {"error": f"bad JSON body: {e}"})
        t = time.time()
        gate = _HEAVY if heavy else None
        if gate:
            gate.acquire()
        try:
            result = handler(body)
            result["_ms"] = round((time.time() - t) * 1000)
            self._json(200, result)
        except KeyError as e:
            self._json(400, {"error": f"missing field {e}"})
        except Exception as e:
            self._json(500, {"error": str(e)[:200]})
        finally:
            if gate:
                gate.release()


def serve(port=8900):
    print(f"pith API → http://127.0.0.1:{port}  ·  max_concurrency={_MAX}")
    print("  POST /extract /contact /intel /directory /profiles /verify-email  ·  GET /health")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8900)
