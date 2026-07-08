"""Control-probe guard: a status-only site that returns 2xx for a JUNK handle can't distinguish a
real user from a fake one (airliners.net, apple-dev forums) — its hits must be suppressed as None.
A site that correctly 404s the junk handle passes real hits through. Tested offline by stubbing the
network probe."""
import pith.profiles as P


def _stub(exists_for):
    """Fake _probe: returns the URL only for handles in `exists_for`, else False."""
    def probe(cfg, handle, timeout):
        return cfg["url"].replace("{}", handle) if handle in exists_for else False
    return probe


def _run(cfg, handle, exists_for, monkeypatch):
    monkeypatch.setattr(P, "_probe", _stub(exists_for))
    P._DISTINGUISHES.clear()                     # cache is per-run; reset between cases
    return P._check(cfg, handle, timeout=5)


def test_2xx_everything_site_suppressed(monkeypatch):
    cfg = {"errorType": "status_code", "url": "https://x/user/{}"}
    junk = P.re.sub(r"[^A-Za-z0-9]", "", P._JUNK_HANDLE) or "znxqp7wk4d2f0a"
    # site "exists" for BOTH the junk control and the real handle -> can't distinguish -> None
    assert _run(cfg, "realuser", {junk, "realuser"}, monkeypatch) is None


def test_reliable_site_passes(monkeypatch):
    cfg = {"errorType": "status_code", "url": "https://x/user/{}"}
    # junk correctly does NOT exist -> site is trusted -> real hit returned
    assert _run(cfg, "realuser", {"realuser"}, monkeypatch) == "https://x/user/realuser"


def test_reliable_site_negative(monkeypatch):
    cfg = {"errorType": "status_code", "url": "https://x/user/{}"}
    assert _run(cfg, "nouser", set(), monkeypatch) is False


def test_message_type_skips_control(monkeypatch):
    # content-check sites read the body -> not the false-positive class -> no control probe
    cfg = {"errorType": "message", "url": "https://x/{}", "errorMsg": "not found"}
    assert _run(cfg, "realuser", {"realuser"}, monkeypatch) == "https://x/realuser"
