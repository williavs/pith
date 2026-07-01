"""Recipes — the à la carte JUDGMENT layer over pith's evidence.

pith's core returns evidence, never answers (see evidence.py). But most apps eventually need a
call: "which email do I use?", "is this the same person?". That call is the APPLICATION's to
make — its intent (sales vs investigation) and its quals (what counts as qualified) differ.

Recipes are pure, transparent, parameterized functions over `Fact` evidence that express the
COMMON judgments — so an app doesn't rewrite them, but can see exactly how the pick was made
and override the criteria. The judgment is never hidden in the core; it lives here, in the
open, tuned by the caller. Nothing here fetches or mutates — evidence in, a decision out.

    owner_email(facts, prefer=...)     # the email to reach the owner, by YOUR preference order
    rank_phones(facts, area_code=...)  # phones ranked by corroboration, optionally your-region-only
    accept_identity(signals, ...)      # threshold resolve's signals with YOUR rules (self-excluded, host-aliased)
    qualify(contact, require=...)      # does this lead meet YOUR bar?
"""
from __future__ import annotations


# --- contact recipes (over Fact evidence, kind="email"/"phone") ---

def owner_email(facts, prefer=("owner", "person", "role")):
    """The best email to reach a decision-maker, by the caller's preference over the transparent
    `email_type` label, then corroboration. Returns the Fact (with its sources) or None — never
    a bare string, so you keep the provenance. `prefer` is YOUR qual: a sales rep might want
    ('owner','person'); a support tool might want ('role',)."""
    emails = [f for f in facts if f.kind == "email"]
    if not emails:
        return None
    rank = {t: i for i, t in enumerate(prefer)}
    scored = [f for f in emails if f.labels.get("email_type") in rank]
    if not scored:
        return None
    return min(scored, key=lambda f: (rank[f.labels["email_type"]], -f.corroboration, f.value))


def rank_phones(facts, area_code=None, min_corroboration=1):
    """Phones ranked by corroboration (how many sources agree). Optionally keep only your
    business's `area_code` — the fix for a scrape that returns 6 numbers across 4 area codes:
    the caller, who knows the business is in 316, filters to 316. Returns Facts, ranked, all of
    them (never one PICK) — you decide where to cut."""
    phones = [f for f in facts if f.kind == "phone" and f.corroboration >= min_corroboration]
    if area_code:
        ac = str(area_code)
        phones = [f for f in phones if _area_code(f.value) == ac]
    return sorted(phones, key=lambda f: (-f.corroboration, f.value))


def _area_code(phone: str) -> str:
    import re
    d = re.sub(r"\D", "", phone)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    return d[:3] if len(d) == 10 else ""


# --- people / roster recipe (over Fact evidence, kind="name") ---

# relationships that are a third party to the page (review author, publisher), not the org's
# own people — excluded from the default roster, but present in the facts if you want them.
_THIRD_PARTY = frozenset({"author", "creator", "reviewer", "commenter", "contributor",
                          "publisher", "sponsor", "brand", "funder", "provider", "copyrightholder"})


def people(facts, include_third_party=False):
    """The named people the core surfaced (schema.org Person on team/leadership/about pages),
    with titles + provenance, deduped by name and ranked by corroboration. The core hides
    nothing — every Person is in `facts` labeled with its `rel`; this recipe just excludes
    third parties (a review author) from the default roster. Pass include_third_party=True to
    keep them (a journalist wants the author). Empty roster = the site has no machine-readable
    team, the honest boundary of deterministic no-LLM extraction, not a silent miss."""
    out = []
    for f in facts:
        if f.kind != "name" or not f.value:
            continue
        if not include_third_party and (f.labels or {}).get("rel") in _THIRD_PARTY:
            continue
        out.append({"name": f.value, "title": (f.labels or {}).get("title", ""),
                    "rel": (f.labels or {}).get("rel", ""), "corroboration": f.corroboration,
                    "sources": sorted({s.url for s in f.sources})})
    return sorted(out, key=lambda p: (-p["corroboration"], p["name"]))


# --- identity recipe (over resolve's corroboration signals) ---

def accept_identity(corroborations, min_signals=2, exclude_self=True, alias_hosts=True):
    """Threshold identity corroboration with YOUR rules — not a hidden 0.67 scalar.

    `corroborations` is a list of {candidate_url, signals:[{name, source_url}]}. This applies
    the rules two real investigators asked for, but as VISIBLE, caller-owned quals:
      - exclude_self: a signal whose source_url IS the candidate's own page is a self-reference,
        not independent corroboration — dropped (the fake-BACKLINK bug, now a knob).
      - alias_hosts: x.com and twitter.com (etc.) are the same host — so a real cross-link is
        not lost to a hostname mismatch (the silent-false-negative bug, now a knob).
      - min_signals: accept only candidates with at least this many INDEPENDENT signals.
    Returns the accepted candidates with their surviving signals — you see exactly why."""
    out = []
    for c in corroborations:
        cand = _canon_host_url(c["candidate_url"], alias_hosts)
        indep = []
        for s in c.get("signals", []):
            src = _canon_host_url(s.get("source_url", ""), alias_hosts)
            if exclude_self and src and src == cand:
                continue                       # self-reference is not corroboration
            indep.append(s)
        if len(indep) >= min_signals:
            out.append({"candidate_url": c["candidate_url"], "signals": indep, "count": len(indep)})
    return sorted(out, key=lambda c: -c["count"])


_HOST_ALIASES = {"x.com": "twitter.com", "fb.com": "facebook.com", "m.facebook.com": "facebook.com"}


def _canon_host_url(url: str, alias: bool) -> str:
    from urllib.parse import urlsplit
    sp = urlsplit((url or "").lower())
    host = sp.netloc.replace("www.", "")
    if alias:
        host = _HOST_ALIASES.get(host, host)
    return host + sp.path.rstrip("/")


# --- qualification recipe (GTM) ---

def qualify(contact: dict, require=("email",), max_grade=None):
    """Does a contact-evidence result meet the caller's bar? `require` is a set of fact kinds
    that must be present (e.g. ('email',) or ('email','phone')); `max_grade` optionally caps
    site modernness (for the dated-site agency pitch). Pure predicate — the app's ICP, not
    pith's opinion."""
    kinds = {f["kind"] if isinstance(f, dict) else f.kind for f in contact.get("facts", [])}
    if not all(k in kinds for k in require):
        return False
    if max_grade is not None:
        grade = contact.get("grade")
        order = "FDCBA"
        if grade in order and order.index(grade) > order.index(max_grade):
            return False
    return True
