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

_WAF = ("challenge-error-text", "AwsWafIntegration.forceRefreshToken", "perimeterxIdentifiers",
        "cf-browser-verification")
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


def _check(cfg: dict, handle: str, timeout: int):
    """One site -> profile URL if the handle CLAIMED it, False if available, None if
    inconclusive (illegal handle / WAF / error). Reimplemented from Sherlock's algorithm."""
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


def enumerate_profiles(handle: str, persona: str | None = None, kind: str | None = None,
                       sites: list[str] | None = None, all_sites: bool = False,
                       data: str | None = None, workers: int = 25, timeout: int = 10) -> list[dict]:
    """Handle -> the public profiles that exist, tagged by GTM value. Existence only —
    run each through resolve.py to confirm it's the TARGET before trusting it."""
    sd = load_sites(data)
    names = _pick(sd, persona, kind, sites, all_sites)

    def one(name):
        url = _check(sd[name], handle, timeout)
        if not url:
            return None
        tag = GTM_SITES.get(name, ("other", "-", False, ""))
        return {"site": name, "url": url, "kind": tag[0], "value": tag[1],
                "recency": tag[2], "gets": tag[3]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        hits = [h for h in pool.map(one, names) if h]
    # curated/valuable first, then the long tail
    order = {"high": 0, "med": 1, "low": 2, "-": 3}
    return sorted(hits, key=lambda h: (order.get(h["value"], 3), h["kind"], h["site"]))
