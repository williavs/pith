"""Identity corroboration — is a CLAIMED profile actually the TARGET, or a handle collision?

Existence (profiles.py) is not identity. This fetches a candidate profile, extracts what it
can deterministically, and scores corroboration against the target's known facts — the same
waterfall idea as phone source-counting. No LLM.

Signals (corroboration count C):
  BACKLINK       +2  candidate links back to a known-good profile of the target (decisive)
  COMPANY-DOMAIN +1  the target's company domain appears in the profile's links/emails
  FULL-NAME      +1  the profile's OWNER name matches the target's name
  SHARED-CONTACT +1  an email/phone on the profile matches one we already have for the target
Verdict: C>=2 ACCEPT · C==1 REVIEW · else REJECT. Only ACCEPT is surfaced by default.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class Target:
    name: str = ""
    company: str = ""
    website: str = ""
    anchors: set = field(default_factory=set)   # known-good profile URLs for this person
    emails: set = field(default_factory=set)
    phones: set = field(default_factory=set)


def _norm_url(u: str) -> str:
    sp = urlsplit((u or "").lower())
    return sp.netloc.replace("www.", "") + sp.path.rstrip("/")


def _owner_name(r) -> str:
    """The profile's owner name — schema Person -> og:title -> title. OWNER SLOT ONLY: a name
    in body text can be a different person, so we never read it."""
    for e in r.structured:
        types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
        if "Person" in types and e.get("name"):
            return str(e["name"])
    return r.meta.get("title") or r.title or ""


def score(target: Target, r) -> dict:
    """Score one fetched candidate Result against the target. Returns verdict + signals."""
    from .cli import _registrable, _name_toks
    owner = _owner_name(r)
    same = set(r.socials)
    for e in r.structured:
        sa = e.get("sameAs")
        if sa:
            same |= set(sa if isinstance(sa, list) else [sa])
        if e.get("url"):
            same.add(str(e["url"]))
    page_domains = {_registrable(u) for u in same} | {em.split("@")[-1] for em in r.emails}

    signals = []
    if {_norm_url(u) for u in same} & {_norm_url(a) for a in target.anchors}:
        signals.append("BACKLINK")
    if target.website and _registrable(target.website) in page_domains:
        signals.append("COMPANY-DOMAIN")
    toks = _name_toks(target.name)
    if toks and owner and all(t in owner.lower() for t in toks):
        signals.append("FULL-NAME")
    if (set(r.emails) & target.emails) or (set(r.phones) & target.phones):
        signals.append("SHARED-CONTACT")

    c = 2 * ("BACKLINK" in signals) + sum(s in signals for s in ("COMPANY-DOMAIN", "FULL-NAME", "SHARED-CONTACT"))
    verdict = "ACCEPT" if c >= 2 else "REVIEW" if c == 1 else "REJECT"
    return {"owner_name": owner, "verdict": verdict, "confidence": round(min(c / 3, 1.0), 2),
            "signals": signals, "links": sorted(_norm_url(u) for u in same)}


def resolve_person(handle, target: Target, persona=None, all_sites=False, workers=6) -> dict:
    """The whole person: enumerate + corroborate profiles, then apply cross-link boost — a
    profile another verified profile links TO is mutually corroborated (REVIEW -> ACCEPT).
    Returns the verified profiles + an overall confidence + the best channels to reach them."""
    hits = resolve_profiles(handle, target, persona=persona, all_sites=all_sites,
                            include_review=True, workers=workers)
    by_url = {_norm_url(h["url"]): h for h in hits}
    for h in hits:                                    # who links to whom
        for link in h.get("links", []):
            if link in by_url and link != _norm_url(h["url"]):
                by_url[link]["_xlinks"] = by_url[link].get("_xlinks", 0) + 1
    for h in hits:                                    # a cross-linked REVIEW becomes ACCEPT
        x = h.get("_xlinks", 0)
        if x:
            h["signals"] = h.get("signals", []) + [f"XLINK({x})"]
            h["confidence"] = round(min(1.0, h["confidence"] + 0.34 * x), 2)
            if h["verdict"] == "REVIEW":
                h["verdict"] = "ACCEPT"
    accepted = [h for h in hits if h["verdict"] == "ACCEPT"]
    rank = {"high": 0, "med": 1, "low": 2, "-": 3}
    channels = sorted(accepted, key=lambda h: (rank.get(h["value"], 3), not h.get("recency")))
    overall = round(min(1.0, 0.4 + 0.15 * len(accepted)), 2) if accepted else 0.0
    return {"handle": handle, "confidence": overall,
            "profiles": sorted(accepted, key=lambda h: (-h["confidence"], h["site"])),
            "best_channels": [c["site"] for c in channels[:3]]}


def resolve_profiles(handle, target: Target, persona=None, all_sites=False, sites=None,
                     include_review=False, workers=6):
    """Enumerate the handle's public profiles, then corroborate each against the target.
    Returns hits with a verdict; ACCEPT-only unless include_review. Fetches candidates
    concurrently (tier-aware via Extractor)."""
    from concurrent.futures import ThreadPoolExecutor
    from .core import Extractor
    from .profiles import enumerate_profiles
    hits = enumerate_profiles(handle, persona=persona, all_sites=all_sites, sites=sites)
    ex = Extractor()

    def check(h):
        out = ex.extract([h["url"]])
        if not out.results:
            return {**h, "verdict": "REJECT", "confidence": 0.0, "signals": []}
        return {**h, **score(target, out.results[0])}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        scored = list(pool.map(check, hits))
    keep = {"ACCEPT"} | ({"REVIEW"} if include_review else set())
    return sorted([s for s in scored if s["verdict"] in keep],
                  key=lambda s: (-s["confidence"], s["site"]))
