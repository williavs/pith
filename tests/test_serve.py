"""HTTP layer of the pith API server — routing, JSON, error codes. No external network
(uses /health, /verify-email, and a missing-field 400), so it runs in the offline suite."""
import json
import threading
import urllib.error
import urllib.request

from http.server import ThreadingHTTPServer

from pith.serve import Handler


def _server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)      # port 0 = ephemeral
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def _post(port, path, body):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.load(r)


def test_health_and_verify():
    srv, port = _server()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            h = json.load(r)
        assert h["status"] == "ok" and h["service"] == "pith"
        code, d = _post(port, "/verify-email", {"email": "jane@acme.com"})
        assert code == 200 and d["valid_syntax"] is True and "_ms" in d
    finally:
        srv.shutdown()


def test_error_codes():
    srv, port = _server()
    try:
        try:                                    # missing required field -> 400
            _post(port, "/intel", {})
            assert False, "expected HTTPError 400"
        except urllib.error.HTTPError as e:
            assert e.code == 400
        try:                                    # unknown endpoint -> 404
            _post(port, "/nope", {})
            assert False, "expected HTTPError 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
