"""Public-profile enumeration — given a handle, which public profiles exist across the web.

Site data is vendored from the Sherlock Project (sherlock-project/sherlock, MIT) as
osint_sites.json; the ~50-line check logic is reimplemented here (not copied) on pith's own
HTTP stack. PUBLIC endpoints only — each check is equivalent to visiting a public profile URL.
No auth, no signup/reset probing, no breach data.

CRITICAL: an existing handle is NOT proof of identity — handle collisions are rampant. This
module reports existence + a GTM value tag; identity corroboration (is it really the target?)
is pith/resolve.py. Surface ACCEPTed hits, not raw existence.

Config vs opinionated: enumerate_profiles(handle) hits the curated GTM subset (opinion);
persona=/kind=/sites=/all_sites=/data= override it (developer control).
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files

from .osint_value import GTM_SITES, curated

# Bot-wall / challenge markers. If a probe returns one of these, the check is INCONCLUSIVE
# (None), never a hit — otherwise a WAF's generic 200 page reads as "profile exists" and
# reports false accounts (e.g. Reddit serves "Please wait for verification" to non-browsers
# for BOTH real and nonexistent handles). Inconclusive is surfaced in coverage, not dropped.
_WAF = ("challenge-error-text", "AwsWafIntegration.forceRefreshToken", "perimeterxIdentifiers",
        "cf-browser-verification", "Please wait for verification", "Just a moment",
        "Checking your browser", "Enable JavaScript and cookies to continue")
_SITES = None


def load_sites(data: str | None = None) -> dict:
    """The vendored site manifest (or a caller-supplied JSON path). Drops the $schema key."""
    global _SITES
    if data:
        raw = json.loads(open(data).read())
    else:
        if _SITES is None:
            _SITES = json.loads(files("pith").joinpath("osint_sites.json").read_text())
        raw = _SITES
    return {k: v for k, v in raw.items() if not k.startswith("$") and isinstance(v, dict)}


def _pick(sites: dict, persona, kind, only, all_sites) -> list[str]:
    names = list(sites)
    if only:                                   # explicit site list — full control
        return [s for s in only if s in sites]
    if all_sites:                              # literally everything, including adult
        return names
    if kind:                                   # only the recognised sites of this data type
        return [s for s in GTM_SITES if s in sites and GTM_SITES[s][0] == kind]
    if persona:                                # focused persona route
        return curated(names, persona)
    # permissive default: EVERY site except adult — the long tail carries real hooks. Value
    # tags (GTM_SITES) rank/route the recognised ones; the rest surface as "other", not dropped.
    return [s for s in names if not sites[s].get("isNSFW")]


def _probe(cfg: dict, handle: str, timeout: int):
    """Raw Sherlock-style decision: profile URL if the handle exists, False if not, None if
    inconclusive (illegal handle / WAF / error)."""
    rc = cfg.get("regexCheck")
    if rc and not re.search(rc, handle):
        return None                            # handle can't exist on this site
    url = cfg["url"].replace("{}", handle)
    probe = cfg["urlProbe"].replace("{}", handle) if cfg.get("urlProbe") else url
    et = cfg.get("errorType")
    method = cfg.get("request_method", "GET")
    try:
        from curl_cffi import requests as creq
        kw = {"impersonate": "chrome", "timeout": timeout,
              "allow_redirects": et != "response_url"}
        if cfg.get("headers"):
            kw["headers"] = cfg["headers"]
        if cfg.get("request_payload"):
            kw["json"] = json.loads(json.dumps(cfg["request_payload"]).replace("{}", handle))
        r = creq.request(method, probe, **kw)
    except Exception:
        return None
    body = r.text or ""
    if any(w in body for w in _WAF):
        return None                            # bot wall — can't tell
    st = r.status_code
    if et == "message":
        msgs = cfg.get("errorMsg")
        msgs = [msgs] if isinstance(msgs, str) else (msgs or [])
        exists = st == 200 and not any(m in body for m in msgs)
    elif et == "status_code":
        ec = cfg.get("errorCode")
        ec = [ec] if isinstance(ec, int) else (ec or [])
        exists = 200 <= st < 300 and st not in ec
    elif et == "response_url":
        exists = 200 <= st < 300
    else:
        exists = st == 200
    return url if exists else False


# status-only detection ("does it return 2xx?") false-positives on sites that serve 2xx for
# non-existent users too (SPAs that render "not found" client-side, 202 bot-interstitials like
# airliners.net, apple developer forums). Content-checking (`message`) sites read the body, so
# they distinguish; status-only sites don't. Guard them with a one-time control probe.
_STATUS_ONLY = frozenset({"status_code", "response_url", None})
_DISTINGUISHES: dict = {}   # cfg url -> bool: does a junk handle correctly NOT exist?
_JUNK_HANDLE = "zqx7w* no such user *4f9k"  # implausible; sanitized per-site below


def _check(cfg: dict, handle: str, timeout: int):
    """One site -> profile URL if the handle CLAIMED it, False if available, None if inconclusive.
    For status-only sites, first confirm the site can actually tell a real handle from a fake one
    (cached) — if a junk handle also 'exists', the site 2xx's everything and its hits are noise."""
    et = cfg.get("errorType")
    if et in _STATUS_ONLY:
        url = cfg["url"]
        if url not in _DISTINGUISHES:
            junk = re.sub(r"[^A-Za-z0-9]", "", _JUNK_HANDLE) or "znxqp7wk4d2f0a"
            ctrl = _probe(cfg, junk, timeout)
            _DISTINGUISHES[url] = not isinstance(ctrl, str)   # unreliable iff a junk handle "exists"
        if not _DISTINGUISHES[url]:
            return None                        # site can't distinguish -> its hits are false positives
    return _probe(cfg, handle, timeout)


# role/bot/reserved usernames that exist on many platforms but are NOT a person — surfacing
# them as high-value contacts misleads an investigator, so hits get flagged reserved=True.
_RESERVED_HANDLES = frozenset({
    "admin", "administrator", "root", "test", "test1", "user", "guest", "info", "support",
    "help", "contact", "mail", "email", "webmaster", "postmaster", "hostmaster", "abuse",
    "null", "none", "anonymous", "anon", "nobody", "system", "daemon", "bot", "api", "dev",
    "demo", "example", "sample", "staff", "team", "sales", "marketing", "noreply", "no-reply",
    "official", "me", "you", "home", "login", "signup",
})
_VALID_HANDLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def enumerate_profiles(handle: str, persona: str | None = None, kind: str | None = None,
                       sites: list[str] | None = None, all_sites: bool = False,
                       data: str | None = None, workers: int = 25, timeout: int = 10,
                       report: bool = False):
    """Handle -> the public profiles that exist, tagged by GTM value. Existence only —
    run each through resolve.py to confirm it's the TARGET before trusting it.

    Reserved/bot handles (admin, test, info...) are enumerated but each hit is flagged
    reserved=True. An invalid handle (URL-breaking chars, path traversal) raises ValueError.

    report=False (default) returns the list of hits. report=True returns
    {profiles, coverage:{checked, found, not_found, inconclusive, inconclusive_sites}} so an
    investigator SEES what could NOT be checked (WAF/timeout/error) rather than reading a
    silent gap as 'no account here'."""
    handle = (handle or "").strip()
    if not _VALID_HANDLE.match(handle):
        raise ValueError(f"invalid handle {handle!r}: usernames are [A-Za-z0-9._-], 1-64 chars "
                         "(no slashes, spaces, query strings, or path traversal)")
    reserved = handle.lower() in _RESERVED_HANDLES
    sd = load_sites(data)
    names = _pick(sd, persona, kind, sites, all_sites)

    def one(name):
        url = _check(sd[name], handle, timeout)   # str=exists · False=available · None=inconclusive
        if url:
            tag = GTM_SITES.get(name, ("other", "-", False, ""))
            return name, {"site": name, "url": url, "kind": tag[0], "value": tag[1],
                          "recency": tag[2], "gets": tag[3], "reserved": reserved}
        return name, (False if url is False else None)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, names))
    hits = [r for _, r in results if isinstance(r, dict)]
    inconclusive = [n for n, r in results if r is None]
    order = {"high": 0, "med": 1, "low": 2, "-": 3}
    hits.sort(key=lambda h: (order.get(h["value"], 3), h["kind"], h["site"]))
    if not report:
        return hits
    return {"profiles": hits, "coverage": {
        "checked": len(results), "found": len(hits),
        "not_found": sum(1 for _, r in results if r is False),
        "inconclusive": len(inconclusive), "inconclusive_sites": sorted(inconclusive)}}
