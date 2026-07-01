"""Deterministic structured extraction — no LLM, no model, no network. Given a page's raw
HTML (and its clean markdown), pull the fields a developer actually wants off a company /
decision-maker page: emails, phone links, social profiles, and the schema.org / OpenGraph
data the page already embeds for Google. Accuracy over recall — a wrong email is worse than
a missing one, so every extractor filters hard.
"""
from __future__ import annotations

import html as _htmlmod
import json
import re

# Cloudflare "Email Address Obfuscation" replaces mailto: with data-cfemail="HEX". The email
# is XOR-encoded: first byte is the key, each following byte XOR key -> a char. Exact decode,
# no guessing — recovers emails Cloudflare hides (very common on small-biz sites).
_CFEMAIL = re.compile(r'data-cfemail=["\']([0-9a-fA-F]{8,})["\']')


def _decode_cfemail(hexstr: str) -> str:
    try:
        key = int(hexstr[:2], 16)
        out = "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
        return out if _EMAIL.fullmatch(out) else ""
    except (ValueError, IndexError):
        return ""


def cfemails(html: str) -> list[str]:
    """Emails Cloudflare obfuscated behind data-cfemail — recovered by exact XOR decode."""
    return sorted({e for e in (_decode_cfemail(m) for m in _CFEMAIL.findall(html or "")) if e})

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}")
# junk that matches the email shape but isn't a real contact: error trackers, placeholders,
# asset filenames, framework noise.
_EMAIL_JUNK = ("sentry.", "@sentry", "example.", "@example", "wixpress", "@2x", ".png", ".jpg",
               ".gif", ".webp", "your@", "email@example", "name@", "user@", "@domain", "@email",
               "@company", "test@test", "godaddy", "@sentry.io")

# social PROFILE urls only — not share/intent/generic-nav links, not other people's buttons.
_SOCIAL = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?"
    r"(?:linkedin\.com/(?:in|company)/[A-Za-z0-9%_-]+"
    r"|(?:twitter|x)\.com/[A-Za-z0-9_]{2,15}"
    r"|github\.com/[A-Za-z0-9-]+"
    r"|facebook\.com/[A-Za-z0-9.-]+"
    r"|instagram\.com/[A-Za-z0-9._]+)",
    re.I,
)
# handles/paths that are UI, not a person: share buttons, intents, nav, generic pages.
_SOCIAL_JUNK = ("/share", "/intent", "/sharer", "/hashtag/", "/explore", "/home", "/login",
                "/search", "/privacy", "/help", "/about", "/tos", "/policies")
_SOCIAL_HANDLES = {"share", "intent", "home", "login", "search", "explore", "i", "messages",
                   "notifications", "settings", "privacy", "help", "about", "tos", "sharer"}

_TEL = re.compile(r"tel:(\+?[\d][\d\s().-]{5,})")  # explicit phone LINKS
# US/NANP phone shown as text — SEPARATORS REQUIRED between groups, so a contiguous digit run
# (tracking IDs like 0060833459) can't match; only real formatted numbers do.
_PHONE_FMT = re.compile(r"(?<![\d.])(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?![\d.])")

_JSON_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
_ENTITY_TYPES = ("Person", "Organization", "Corporation", "LocalBusiness")
_KEEP = ("@type", "name", "jobTitle", "email", "telephone", "url", "sameAs", "worksFor", "address", "description")

_META = [("og:title", "title"), ("og:description", "description"), ("og:site_name", "site"),
         ("og:type", "type"), ("article:author", "author"), ("article:published_time", "published"),
         ("author", "author")]


def emails(text: str) -> list[str]:
    text = _htmlmod.unescape(text or "")  # decode &#64;/&commat;/&#46; entity-encoded emails first
    return sorted({e for e in _EMAIL.findall(text)
                   if not any(j in e.lower() for j in _EMAIL_JUNK)})


def phones(text: str) -> list[str]:
    """`tel:` links plus formatted NANP numbers (separators required, so tracking-ID digit
    runs don't match). Catches phones shown as plain text in a contact widget/page."""
    tel = {re.sub(r"\s+", " ", t).strip() for t in _TEL.findall(text or "")}
    fmt = {re.sub(r"\s+", " ", p).strip() for p in _PHONE_FMT.findall(text or "")}
    return sorted(tel | fmt)


def _is_profile(url: str) -> bool:
    low = url.lower()
    if any(j in low for j in _SOCIAL_JUNK):
        return False
    handle = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return handle not in _SOCIAL_HANDLES


def socials(text: str) -> list[str]:
    return sorted({m.group(0) for m in _SOCIAL.finditer(text or "") if _is_profile(m.group(0))})


def _iter_entities(data):
    """Walk JSON-LD: unwrap @graph, top-level arrays, and nested objects."""
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if "@graph" in o and isinstance(o["@graph"], list):
                stack.extend(o["@graph"])
            yield o
            stack.extend(v for v in o.values() if isinstance(v, (dict, list)))
        elif isinstance(o, list):
            stack.extend(o)


def structured(html: str) -> list[dict]:
    """schema.org Person/Organization entities the page embeds for Google — the deterministic
    gold for decision-maker/company data: name, jobTitle, email, telephone, sameAs (socials)."""
    out, seen = [], set()
    for block in _JSON_LD.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for e in _iter_entities(data):
            if not isinstance(e, dict):
                continue
            t = e.get("@type")
            types = t if isinstance(t, list) else [t]
            if not any(x in _ENTITY_TYPES for x in types):
                continue
            kept = {k: e[k] for k in _KEEP if k in e}
            key = json.dumps(kept, sort_keys=True, default=str)
            if kept.get("name") and key not in seen:
                seen.add(key)
                out.append(kept)
    return out


def meta(html: str) -> dict:
    """OpenGraph + author/date meta tags."""
    m = {}
    for prop, key in _META:
        mt = re.search(
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
            html or "", re.I)
        if mt and key not in m:
            m[key] = mt.group(1).strip()
    return m


# Role/generic mailbox locals — not a person, a function. Useful to flag for GTM (you'd
# personalize outreach differently to sales@ vs a named person).
_ROLE_LOCALS = frozenset({
    "info", "information", "support", "sales", "admin", "contact", "hello", "team", "noreply",
    "no-reply", "donotreply", "help", "jobs", "careers", "career", "billing", "office", "mail",
    "marketing", "press", "hr", "legal", "abuse", "postmaster", "webmaster", "enquiries",
    "inquiries", "enquiry", "inquiry", "feedback", "service", "services", "orders", "accounts",
    "reception", "scheduling", "dispatch", "estimates", "quotes", "customerservice", "general",
})
# Free/consumer mail + big US ISP domains. On a BUSINESS, a freemail address usually means
# the owner-operator directly (small-mid biz) rather than a corporate mailbox — a high-value
# GTM signal, not noise. (Not exhaustive; the common ones cover most small-biz sites.)
_FREEMAIL = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com", "me.com",
    "protonmail.com", "proton.me", "gmx.com", "mail.com", "live.com", "msn.com", "ymail.com",
    "comcast.net", "att.net", "verizon.net", "sbcglobal.net", "cox.net", "charter.net",
    "bellsouth.net", "earthlink.net", "roadrunner.com", "rr.com", "windstream.net",
})
_DISPOSABLE = None  # lazy-loaded bundled list (4k domains, from MIT umuterturk/email-verifier)


def _disposable() -> frozenset:
    global _DISPOSABLE
    if _DISPOSABLE is None:
        try:
            from importlib.resources import files
            _DISPOSABLE = frozenset(files("pith").joinpath("disposable_domains.txt").read_text().split())
        except Exception:
            _DISPOSABLE = frozenset()
    return _DISPOSABLE


def verify_email(email: str, check_domain: bool = False) -> dict:
    """Deterministic email quality signals — no SMTP probe, no external API, no LLM.
    Reports: valid_syntax, is_role (generic mailbox), is_disposable (throwaway domain),
    has_alias (plus-tag). `check_domain=True` adds a stdlib DNS resolve (network) to catch
    dead/typo domains. NOT a deliverability check — real SMTP verification is unreliable
    (catch-all / greylisting) and risks sender reputation, so it's deliberately omitted."""
    email = (email or "").strip().lower()
    if not _EMAIL.fullmatch(email):
        return {"email": email, "valid_syntax": False}
    local, domain = email.rsplit("@", 1)
    base = local.split("+", 1)[0]
    # ISP subdomains like foo.rr.com / smtp.comcast.net -> treat by their registrable tail
    freemail = domain in _FREEMAIL or any(domain.endswith("." + f) for f in _FREEMAIL)
    out = {"email": email, "valid_syntax": True, "domain": domain,
           "is_role": base in _ROLE_LOCALS, "is_disposable": domain in _disposable(),
           "is_freemail": freemail, "has_alias": "+" in local}
    if check_domain:
        import socket
        try:
            socket.getaddrinfo(domain, None)
            out["domain_resolves"] = True
        except Exception:
            out["domain_resolves"] = False
    return out


def enrich(markdown: str, html: str) -> dict:
    """Everything deterministic, in one call. markdown feeds contact scan (clean text);
    html feeds structured/meta (needs the raw tags)."""
    src = (markdown or "") + "\n" + (html or "")
    st = structured(html)
    tel = phones(html)
    for e in st:  # fold schema.org telephones into phones
        if e.get("telephone"):
            tel.append(str(e["telephone"]))
    # emails: visible/entity-encoded + Cloudflare-obfuscated + any in schema.org
    em = set(emails(src)) | set(cfemails(html))
    for e in st:
        if e.get("email"):
            em |= set(emails(str(e["email"])))
    em = {e for e in em if not any(j in e.lower() for j in _EMAIL_JUNK)}
    return {
        "emails": sorted(em),
        "phones": sorted(set(tel)),
        "socials": socials(src),
        "structured": st,
        "meta": meta(html),
    }
