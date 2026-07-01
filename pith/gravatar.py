"""Gravatar reverse-email pivot — the best LEGAL, deterministic email -> accounts primitive.

Gravatar exposes a PUBLIC profile JSON keyed by the md5 of a lowercased email. If the person
set one up, it hands back their display name, location, bio, and — the OSINT gold — the other
accounts they've verified-linked (Twitter, LinkedIn, GitHub, ...). Public data, no auth, no
scraping. Returns None-ish (exists=False) when there's no public profile for that email.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request


def _hash(email: str) -> str:
    return hashlib.md5(email.strip().lower().encode()).hexdigest()


def gravatar_profile(email: str, timeout: int = 10) -> dict:
    """email -> public Gravatar profile + linked accounts, or {exists: False}. Deterministic,
    public API only. The `accounts` list is the pivot: verified-linked profiles on other
    networks (each with a confidence — Gravatar only lists accounts the owner attached)."""
    email = (email or "").strip().lower()
    if "@" not in email:
        return {"email": email, "exists": False, "error": "not an email"}
    h = _hash(email)
    url = f"https://gravatar.com/{h}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "pith"})
    try:
        data = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"email": email, "hash": h, "exists": False}     # no public gravatar
        return {"email": email, "hash": h, "exists": False, "error": f"http {e.code}"}
    except Exception as e:
        return {"email": email, "hash": h, "exists": False, "error": str(e)[:80]}

    entries = data.get("entry") or []
    if not entries:
        return {"email": email, "hash": h, "exists": False}
    e = entries[0]
    accounts = [{"site": a.get("name") or a.get("shortname"), "url": a.get("url"),
                 "username": a.get("username"), "verified": a.get("verified") in (True, "true")}
                for a in e.get("accounts", []) if a.get("url")]
    urls = [u.get("value") for u in e.get("urls", []) if u.get("value")]
    return {
        "email": email, "hash": h, "exists": True,
        "profile_url": e.get("profileUrl"),
        "display_name": e.get("displayName") or e.get("preferredUsername"),
        "name": (e.get("name") or {}).get("formatted") if isinstance(e.get("name"), dict) else e.get("name"),
        "location": e.get("currentLocation"),
        "about": e.get("aboutMe"),
        "avatar": e.get("thumbnailUrl"),
        "accounts": accounts,          # <- the email->other-accounts pivot
        "urls": urls,
    }
