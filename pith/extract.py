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
import unicodedata
import urllib.parse

# normalize invisibles/unicode BEFORE any phone/email regex — these silently break \d runs.
_DEL = dict.fromkeys(map(ord, "​‌‍‎‏⁠﻿­᠎"), None)  # ZW + soft-hyphen + word-joiner + LRM/RLM
_MAP = {0x00a0: 0x20, 0x2007: 0x20, 0x202f: 0x20}          # nbsp variants -> space
_MAP.update({c: 0x2d for c in range(0x2010, 0x2016)})      # unicode hyphens -> '-'
_MAP[0x2212] = 0x2d                                        # minus sign -> '-'


def _clean(t: str) -> str:
    """Fold away obfuscation that breaks digit/char runs: entities, zero-width/soft-hyphen,
    nbsp, unicode hyphens, fullwidth digits, Arabic-Indic digits. No fabrication."""
    t = _htmlmod.unescape(t or "").translate(_DEL).translate(_MAP)
    t = unicodedata.normalize("NFKC", t)                  # fullwidth ４１５ -> 415
    return "".join(str(unicodedata.digit(c)) if unicodedata.category(c) == "Nd" and not c.isascii() else c
                   for c in t)

# Cloudflare "Email Address Obfuscation" replaces mailto: with data-cfemail="HEX". The email
# is XOR-encoded: first byte is the key, each following byte XOR key -> a char. Exact decode,
# no guessing — recovers emails Cloudflare hides (very common on small-biz sites).
_CFEMAIL = re.compile(r'data-cfemail=["\']([0-9a-fA-F]{6,})["\']')
_CFEMAIL_H = re.compile(r'/cdn-cgi/l/email-protection#([0-9a-fA-F]{6,})')  # Cloudflare-rewritten mailto links


def _decode_cfemail(hexstr: str) -> str:
    if len(hexstr) % 2 or len(hexstr) < 6:  # even-length + >=6 hex floor
        return ""
    try:
        key = int(hexstr[:2], 16)
        out = "".join(chr(int(hexstr[i:i + 2], 16) ^ key) for i in range(2, len(hexstr), 2))
    except ValueError:
        return ""
    if not out.isascii():                   # non-ascii => not the protected email
        return ""
    out = out.lower()
    if not _EMAIL.fullmatch(out) or _junk_email(out):  # junk gate, parity with emails()
        return ""
    return out


# bracketed at/dot only — "sales [at] acme [dot] com". The bare lowercase form ("meet me at
# the dot") is a verified prose false-positive source, so it's deliberately NOT matched.
_ATDOT = re.compile(
    r'([A-Za-z0-9._%+\-]+)\s*[\[({]\s*at\s*[\])}]\s*'
    r'([A-Za-z0-9\-]+(?:\s*[\[({]\s*dot\s*[\])}]\s*[A-Za-z0-9\-]+)*)\s*'
    r'[\[({]\s*dot\s*[\])}]\s*([A-Za-z]{2,18})', re.I)


def atdot_emails(text: str) -> list[str]:
    """Recover emails obfuscated as 'name [at] domain [dot] com' (bracketed markers only)."""
    out = set()
    for m in _ATDOT.finditer(_clean(text)):
        mid = re.sub(r'\s*[\[({]\s*dot\s*[\])}]\s*', '.', m.group(2), flags=re.I)
        cand = f"{m.group(1)}@{mid}.{m.group(3)}".lower()
        if _EMAIL.fullmatch(cand) and not _junk_email(cand):
            out.add(cand)
    return sorted(out)


def cfemails(html: str) -> list[str]:
    """Emails Cloudflare obfuscated behind data-cfemail or /cdn-cgi/l/email-protection# links —
    recovered by exact XOR decode (first hex byte is the key)."""
    html = html or ""
    blobs = set(_CFEMAIL.findall(html)) | set(_CFEMAIL_H.findall(html))
    return sorted({e for e in (_decode_cfemail(b) for b in blobs) if e})

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,18}")  # real TLDs <=18ch
# SAFE substrings — these only ever appear in junk (error trackers, asset filenames, retina
# suffixes), so a substring match won't hit a real address.
_ASSET_JUNK = ("sentry.", "@sentry", "wixpress", "@2x", "@3x", ".png", ".jpg", ".jpeg",
               ".gif", ".webp", ".svg")
# EXACT placeholder local-parts / domains from template boilerplate. Matched whole (not as
# substrings) so a real address like john.lastname@acme.com is NOT dropped by "name@".
# Only locals that are NEVER a real contact — name-like locals (name/user/john.doe/lastname)
# collide with real addresses, so template junk is caught by _PLACEHOLDER_DOMAIN instead.
_PLACEHOLDER_LOCAL = {"your", "yourname", "youremail", "yourusername"}
_PLACEHOLDER_DOMAIN = {"example.com", "example.org", "example.net", "email.com", "domain.com",
                       "company.com", "yourcompany.com", "yourdomain.com", "yoursite.com",
                       "test.com", "sentry.io", "godaddy.com"}
# file extensions that look like a 2-18 char alpha TLD — report@final.doc is a filename, not email.
_FILE_EXT_TLD = {"png", "jpg", "jpeg", "gif", "webp", "svg", "doc", "docx", "pdf", "xls", "xlsx",
                 "ppt", "pptx", "zip", "gz", "mp4", "mov", "css", "js", "json", "html", "htm",
                 "php", "xml", "txt", "csv", "webm", "ico"}


# fediverse instances: user@instance LOOKS exactly like an email but is a Mastodon/Pleroma
# handle (usually surfaced from a rel=me link), not a deliverable address. The big instances
# cover most of it; the long tail is unbounded (ponytail: add on report).
_FEDIVERSE = frozenset({
    "mastodon.social", "mastodon.online", "mas.to", "mstdn.social", "fosstodon.org",
    "hachyderm.io", "techhub.social", "infosec.exchange", "ioc.exchange", "social.lol",
    "mastodon.world", "universeodon.com", "front-end.social", "indieweb.social",
})


# WHOIS privacy-proxy hosts: the "registrant email" is a per-domain hash, never a real contact.
_PROXY_EMAIL = ("whoisproxy", "whoisguard", "privacyprotect", "contactprivacy", "domainsbyproxy",
                "privacyguardian", "withheldforprivacy", "identity-protect", "data-protected",
                "redacted", "proxy.dnstination")


def _junk_email(e: str) -> bool:
    """True if an email-shaped string is template junk, an asset filename, a placeholder, a
    fediverse handle, or a WHOIS privacy-proxy hash — used everywhere emails are emitted."""
    el = e.lower()
    if any(j in el for j in _ASSET_JUNK) or any(p in el for p in _PROXY_EMAIL):
        return True
    local, _, domain = el.partition("@")
    if local in _PLACEHOLDER_LOCAL or domain in _PLACEHOLDER_DOMAIN or domain in _FEDIVERSE:
        return True
    if len(local) >= 40 and re.fullmatch(r"[0-9a-f]+", local):    # 64-char hex local = proxy/obfuscation hash
        return True
    return domain.rsplit(".", 1)[-1] in _FILE_EXT_TLD

# handles/paths that are UI, not a person: share buttons, intents, nav, generic pages,
# tracking pixels (facebook.com/tr), content permalinks (instagram.com/p/, /reel/, /tv/),
# product/marketing pages (github.com/pricing, /features).
_SOCIAL_JUNK = ("/share", "/intent", "/sharer", "/hashtag/", "/explore", "/home", "/login",
                "/search", "/privacy", "/help", "/about", "/tos", "/policies", "/tr", "/p/",
                "/reel", "/reels", "/tv/", "/stories/", "/story/", "/plugins/", "/dialog/",
                "/pricing", "/features", "/marketplace", "/topics", "/sponsors", "/pulls",
                "/issues", "/watch", "/events", "/groups", "/pages/", "/dir/", "?")
# reserved path segments that are pages/products/nav, never a personal or business handle.
_SOCIAL_HANDLES = {
    "share", "intent", "home", "login", "signup", "search", "explore", "i", "messages",
    "notifications", "settings", "privacy", "help", "about", "tos", "terms", "sharer", "tr",
    "p", "reel", "reels", "tv", "stories", "story", "watch", "events", "groups", "pages",
    "plugins", "dialog", "marketplace", "gaming", "live", "accounts", "direct", "web",
    "pricing", "features", "topics", "sponsors", "pulls", "issues", "orgs", "apps",
    "collections", "trending", "new", "join", "contact", "security", "enterprise", "team",
    "business", "developers", "docs", "status", "support", "download", "mobile", "careers",
    "jobs", "blog", "press", "legal", "cookies", "ads", "policies",
    # github marketing/nav slugs (bare-domain chrome that isn't a user)
    "why-github", "accelerator", "customer-stories", "partners", "premium-support", "resources",
    "solutions", "mcp", "readme", "spark", "copilot", "codespaces", "actions", "packages",
}

_TEL = re.compile(r"tel:(\+?[\d][\d\s().-]{5,})")  # explicit phone LINKS
# US/NANP phone shown as text — SEPARATORS REQUIRED between groups, so a contiguous digit run
# (tracking IDs like 0060833459) can't match; only real formatted numbers do.
_PHONE_FMT = re.compile(r"(?<![\d.])(?:\+?1[-.\s])?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?!\d)")
# International: a literal + then a country code and 7-14 more digits (E.164 is +[8..15] digits).
# The leading + is the anchor so this can't grab prices/IDs; digit count is validated in _canon_phone.
_PHONE_INTL = re.compile(r"(?<![\w+])\+\d[\d\s().\-]{6,18}\d(?!\d)")

_JSON_LD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
# An allowlist of schema.org org types is prescriptive — schema has ~100 LocalBusiness subtypes
# (HairSalon, MedicalClinic, AutoRepair, DaySpa, ...) and any not listed lost its whole entity
# (address/rating/hours/contact). Match by KEYWORD instead so subtypes flow through generally.
_ORG_KEYWORDS = ("business", "organization", "corporation", "store", "restaurant", "service",
                 "clinic", "salon", "shop", "agency", "practice", "dealer", "repair", "hotel",
                 "hospital", "school", "bank", "company", "firm", "pharmacy", "cafe", "café",
                 "bakery", "bar", "gym", "spa", "studio", "office", "center", "centre", "provider",
                 "contractor", "market", "resort", "winery", "brewery", "dentist", "attorney",
                 "lawyer", "physician", "medical", "dental", "veterinary", "realtor", "estate")
_ORG_TYPES = ("Organization", "LocalBusiness")   # kept for docs/readability; matching uses keywords


def _is_org_type(types) -> bool:
    """True if any @type looks like a business/org — keyword match over schema.org's many
    LocalBusiness subtypes, so a salon/clinic/auto-shop isn't dropped for not being enumerated."""
    return any(any(kw in str(t).lower() for kw in _ORG_KEYWORDS) for t in types)
# a Person reached via one of these keys is a review/blog author or quoted third party — NOT
# the business owner. Drop them (precision: a wrong person poisons outreach).
_DROP_PARENT = frozenset({"author", "creator", "reviewer", "commenter", "contributor", "publisher"})
# a Person reached via one of these keys IS an owner/staff/subject of the page — keep.
# mainentity/about are the canonical ProfilePage pattern: the subject Person of the page.
_OWNER_PARENT = frozenset({"founder", "owner", "employee", "employees", "member", "members",
                           "contactpoint", "manager", "founders", "director",
                           "mainentity", "about"})
# when a Person has no explicit jobTitle, the schema key they hang off IS their title —
# founder/owner/director are real titles; employee/member are too generic to assert.
_PARENT_TITLE = {"founder": "Founder", "founders": "Founder", "owner": "Owner",
                 "manager": "Manager", "director": "Director"}
# an Organization reached via one of these keys is a third party (site publisher, ad sponsor,
# product brand, grant funder) — NOT the business the page is about. Drop it.
_DROP_ORG_PARENT = frozenset({"publisher", "sponsor", "brand", "funder", "provider",
                              "author", "creator", "copyrightholder"})
# entities reached via these keys are third parties (review author, site publisher, ad sponsor).
# structured() KEEPS them (labeled rel=...); a consumer scoping "the business's OWN contact"
# skips them — the data is surfaced, only the attribution is scoped.
_THIRD_PARTY_REL = _DROP_PARENT | _DROP_ORG_PARENT
# Don't curate a field allowlist (prescriptive — it silently drops openingHours, aggregateRating,
# priceRange, geo, foundingDate, numberOfEmployees the business already published for free). Keep
# every scalar/list field, plus the nested dicts downstream consumes, and flatten the high-value
# nested objects to clean values.
_DROP_FIELDS = frozenset({"@context", "@id", "@graph", "mainEntityOfPage", "potentialAction"})
_KEEP_NESTED = ("address", "worksFor", "contactPoint")   # dicts downstream reads


def _fmt_hours(spec) -> str:
    """openingHoursSpecification (list of {dayOfWeek, opens, closes}) -> 'Mo 09:00-17:00; ...'."""
    out = []
    for s in spec if isinstance(spec, list) else [spec]:
        if not isinstance(s, dict):
            continue
        d = s.get("dayOfWeek", "")
        d = ",".join(str(x).split("/")[-1][:2] for x in d) if isinstance(d, list) else str(d).split("/")[-1][:2]
        o = s.get("opens", "")
        if d and o:
            out.append(f"{d} {o}-{s.get('closes', '')}")
    return "; ".join(out)


def _simplify(e: dict) -> dict:
    """schema.org entity -> its useful data, WITHOUT a prescriptive field list. Every scalar and
    list-of-scalars passes through (general: new fields aren't lost), the nested contact dicts are
    kept, and the high-value nested objects (rating, geo, hours) are flattened to clean scalars."""
    out = {k: v for k, v in e.items()
           if k not in _DROP_FIELDS
           and (isinstance(v, (str, int, float, bool)) or (isinstance(v, list) and all(isinstance(x, str) for x in v)))}
    for k in _KEEP_NESTED:
        if k in e and k not in out:
            out[k] = e[k]
    ar = e.get("aggregateRating")
    if isinstance(ar, dict) and ar.get("ratingValue"):
        out["rating"] = str(ar["ratingValue"])
        if ar.get("reviewCount") or ar.get("ratingCount"):
            out["review_count"] = str(ar.get("reviewCount") or ar.get("ratingCount"))
    geo = e.get("geo")
    if isinstance(geo, dict) and geo.get("latitude"):
        out["lat"], out["lon"] = str(geo["latitude"]), str(geo.get("longitude", ""))
    if not out.get("hours"):
        oh = e.get("openingHours")
        if isinstance(oh, str):
            out["hours"] = oh
        elif isinstance(oh, list):
            out["hours"] = "; ".join(x for x in oh if isinstance(x, str))
        elif e.get("openingHoursSpecification"):
            out["hours"] = _fmt_hours(e["openingHoursSpecification"])
    return out

_META = [("og:title", "title"), ("og:description", "description"), ("og:site_name", "site"),
         ("og:type", "type"), ("article:author", "author"), ("article:published_time", "published"),
         ("author", "author")]


def emails(text: str) -> list[str]:
    text = _clean(text)  # decode entities + fold invisibles before matching
    return sorted({e for e in _EMAIL.findall(text) if not _junk_email(e)})


def _canon_phone(p: str):
    """Canonicalize a phone to one form so the same number doesn't appear 5 ways.
    Returns '(xxx) xxx-xxxx' for a valid 10-digit NANP, '+<digits>' (E.164) for an
    international number (leading + and 8-15 digits), '' for a recognized placeholder to
    DROP (area code 555 — not an assignable NANP NPA, so it's fiction like (555) 555-5555),
    or None for anything else (kept as-is)."""
    intl = "+" in p
    d = re.sub(r"\D", "", p)
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) == 10 and d[0] not in "01" and d[3] not in "01":  # valid NANP area/exchange
        if d[:3] == "555":                                      # 555 is not a real area code
            return ""
        return f"({d[:3]}) {d[3:6]}-{d[6:]}"
    if intl and 8 <= len(d) <= 15:                              # international, E.164-normalized
        return "+" + d
    return None


def phones(text: str) -> list[str]:
    """`tel:` links plus formatted NANP numbers (separators required, so tracking-ID digit
    runs don't match). Normalizes invisibles/unicode first; canonicalizes + dedups NANP so
    one phone appears once. Recognized placeholders (555 area code) are dropped."""
    text = _clean(text)
    raw = {re.sub(r"\s+", " ", t).strip() for t in _TEL.findall(text)}
    raw |= {re.sub(r"\s+", " ", p).strip() for p in _PHONE_FMT.findall(text)}
    raw |= {re.sub(r"\s+", " ", p).strip() for p in _PHONE_INTL.findall(text)}
    # Only emit CANONICAL numbers (valid NANP or +E.164). A formatted triple that fails NANP
    # validation (area/exchange starting 0 or 1) is a SKU / invoice / part number, not a phone —
    # dropping it beats leaking a false contact. c == "" is a recognized placeholder (555), also dropped.
    return sorted({c for c in (_canon_phone(p) for p in raw) if c})


def _is_profile(url: str) -> bool:
    low = url.lower()
    if any(j in low for j in _SOCIAL_JUNK):
        return False
    handle = url.rstrip("/").rsplit("/", 1)[-1].lower()
    return handle not in _SOCIAL_HANDLES


# Core apex-style platforms (profile at host/{user}) — present even if the OSINT sitelist can't load.
_CORE_APEX = frozenset({
    "linkedin.com", "twitter.com", "x.com", "github.com", "gitlab.com", "facebook.com",
    "instagram.com", "youtube.com", "tiktok.com", "threads.net", "bsky.app", "medium.com",
    "reddit.com", "pinterest.com", "behance.net", "dribbble.com", "twitch.tv", "vimeo.com",
    "soundcloud.com", "patreon.com", "crunchbase.com", "mastodon.social",
})
_HOSTS: tuple | None = None          # (apex: frozenset, sub: frozenset)
_URL_RE = re.compile(r"https?://[^\s\)\]\}\"'<>]+", re.I)


def _profile_hosts() -> tuple:
    """(apex, sub) host sets from the OSINT sitelist (~480 sites) + core platforms. A site's URL
    pattern tells us which: `host/{}` -> apex (reject subdomains like docs.github.com); `{}.host`
    -> sub (the subdomain IS the profile, jane.substack.com). Loaded once."""
    global _HOSTS
    if _HOSTS is None:
        apex, sub = set(_CORE_APEX), {"substack.com", "tumblr.com", "wordpress.com", "medium.com"}
        try:
            from .profiles import load_sites
            for site in load_sites().values():
                pat = site.get("url", "") or site.get("urlMain", "")
                netloc = urllib.parse.urlsplit(pat).netloc.lower()
                if "{}" in netloc:                       # {user}.host  -> subdomain profile
                    sub.add(netloc.split("}.")[-1].lstrip("."))
                else:
                    h = netloc[4:] if netloc.startswith("www.") else netloc
                    if h:
                        apex.add(h)
        except Exception:
            pass
        _HOSTS = (frozenset(apex), frozenset(sub))
    return _HOSTS


def _host_known(host: str, apex: frozenset, sub: frozenset) -> bool:
    host = host.lower()
    if host.startswith(("www.", "m.", "mobile.")):
        host = host.split(".", 1)[1]
    if host in apex:                                     # exact apex host (github.com), not a subdomain
        return True
    return any(host == b or host.endswith("." + b) for b in sub)   # subdomain profile


def socials(text: str) -> list[str]:
    """Every link to a known profile/social platform, minus share/nav/login junk. Raw by design:
    matches the full OSINT sitelist so TikTok/YouTube/Behance/etc. are recognized, not just the old
    five — the caller filters to the platforms it wants. Apex platforms reject subdomains (docs.
    github.com isn't a profile); subdomain platforms keep them (jane.substack.com). ponytail:
    host-match still keeps some content links on known platforms (a Medium article) — caller drops
    those, pith hides nothing."""
    apex, sub = _profile_hosts()
    out = set()
    for m in _URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(".,);]!’'\"")
        host = urllib.parse.urlsplit(u).netloc
        if host and _host_known(host, apex, sub) and _is_profile(u):
            out.add(u)
    return sorted(out)


def _walk_entities(data):
    """Walk JSON-LD yielding (entity, parent_key). parent_key is '' for a top-level or
    @graph-member entity; otherwise the key it hangs off (author/founder/review/...), which
    tells us whether a Person is the owner or just a quoted third party."""
    stack = [(data, "", True)]  # (node, parent_key, is_top_or_graph)
    while stack:
        node, pkey, top = stack.pop()
        if isinstance(node, dict):
            graph = node.get("@graph")
            if isinstance(graph, list):
                for g in graph:
                    stack.append((g, "", True))
            yield node, ("" if top else pkey)
            for k, v in node.items():
                if k != "@graph" and isinstance(v, (dict, list)):
                    stack.append((v, k.lower(), False))
        elif isinstance(node, list):
            for x in node:
                stack.append((x, pkey, top))


def structured(html: str) -> list[dict]:
    """schema.org Person/Organization entities the page embeds for Google — the deterministic
    gold for decision-maker/company data: name, jobTitle, email, telephone, sameAs (socials)."""
    out, seen = [], set()
    for block in _JSON_LD.findall(html or ""):
        try:
            data = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            try:  # lenient reparse: WordPress often emits trailing commas
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", block.strip()))
            except (json.JSONDecodeError, ValueError):
                continue
        for e, pkey in _walk_entities(data):
            if not isinstance(e, dict):
                continue
            types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
            is_person = "Person" in types
            is_org = _is_org_type(types)
            if not (is_person or is_org):
                continue
            # Keep EVERY real entity — never hide data. Tag its relationship to the page so a
            # consumer can scope (a review author, a publisher org) WITHOUT the core deciding
            # for them. `rel`: "" = top-level/@graph (the page's subject); else the parent key.
            kept = _simplify(e)
            kept["rel"] = pkey
            if is_person and not kept.get("jobTitle") and pkey in _PARENT_TITLE:
                kept["jobTitle"] = _PARENT_TITLE[pkey]   # schema placed them under founder/owner/... = their title
            key = json.dumps(kept, sort_keys=True, default=str)
            if kept.get("name") and key not in seen:
                seen.add(key)
                out.append(kept)
    return out


def firmographics(structured: list[dict]) -> dict:
    """A business's OWN free firmographics from its schema.org Org/LocalBusiness entity — rating,
    review_count, hours, price, founded, employees, geo — whatever it published. These are the
    fields the old field-allowlist silently dropped; often present on local-business sites for free
    (fills the rating/hours/founded/employees 'gaps' without a keyed API)."""
    want = ("rating", "review_count", "hours", "priceRange", "foundingDate",
            "numberOfEmployees", "lat", "lon", "areaServed")
    got: dict = {}
    for e in structured:                       # merge across all org entities (rating + hours often split)
        types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
        if _is_org_type(types):
            for k in want:
                if e.get(k) and k not in got:
                    got[k] = e[k]
    return got


def _assemble_address(addr) -> str:
    """schema.org address (object or string) -> 'street, City ST ZIP'. Emits only when >=2 of
    {street, locality, postal} are present (kills country-only / zip-only false positives)."""
    if isinstance(addr, str):
        return addr.strip() if len(addr.strip()) > 8 else ""
    if not isinstance(addr, dict):
        return ""
    street = addr.get("streetAddress")
    if isinstance(street, list):
        street = ", ".join(str(s) for s in street)
    loc, reg, zp = addr.get("addressLocality"), addr.get("addressRegion"), addr.get("postalCode")
    if sum(bool(x) for x in (street, loc, zp)) < 2:
        return ""
    cityline = " ".join(str(x) for x in (loc, reg, zp) if x)
    return ", ".join(p for p in (str(street) if street else "", cityline) if p)


def addresses(html: str) -> list[str]:
    """Business street address from schema.org (the parentage-scoped primary org only)."""
    out = []
    for e in structured(html):
        types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
        if "Person" not in types:  # org address, not a person's
            a = _assemble_address(e.get("address"))
            if a:
                out.append(a)
    return sorted(set(out))


def meta(html: str) -> dict:
    """EVERY og:/twitter:/meta property the page publishes — raw, so the caller filters, not pith.
    The old allowlist dropped free contact/price data (`business:contact_data:*`, `og:price:amount`,
    `og:image`, `twitter:*`). Friendly aliases (title/description/site/type/author/published) are
    kept for back-compat, set from the raw og:* keys."""
    m = {}
    for tag in re.finditer(r"<meta\b[^>]*>", html or "", re.I):
        t = tag.group(0)
        k = re.search(r'(?:property|name)=["\']([^"\']+)', t, re.I)
        v = re.search(r'content=["\']([^"\']*)', t, re.I)
        if k and v:
            key, val = k.group(1).strip(), v.group(1).strip()
            if key and val and key not in m:
                m[key] = val
    for prop, key in _META:                 # back-compat aliases over the raw keys
        if prop in m and key not in m:
            m[key] = m[prop]
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


def _email_syntax_ok(email: str) -> bool:
    """Unicode-aware syntax check for a KNOWN address (SMTPUTF8/IDN allowed) — distinct from
    the conservative ASCII `_EMAIL` extractor, which scans noisy body text. Accepts
    josé@example.com and 用户@例子.公司; rejects spaces, empty parts, dotless/short TLDs."""
    if email.count("@") != 1 or len(email) > 254:          # RFC 5321 total length cap
        return False
    local, domain = email.split("@")
    if not local or len(local) > 64 or any(c.isspace() for c in local) or ".." in email:
        return False
    labels = domain.split(".")
    if len(labels) < 2 or any(not lb or any(c.isspace() for c in lb) for lb in labels):
        return False
    tld = labels[-1]
    if tld.startswith("xn--"):                       # punycode IDN TLD (.рф etc.)
        return len(tld) > 4
    return len(tld) >= 2 and tld.replace("-", "").isalpha()   # .isalpha() is unicode-aware


import functools


def _dns_resolver():
    """A dnspython resolver with a SHORT budget — a dead domain must fail in ~3s, not block ~20s on
    the OS default (which tanks throughput when a stale list has thousands of dead domains)."""
    import dns.resolver
    r = dns.resolver.Resolver()
    r.timeout = r.lifetime = 3.0
    return r


@functools.lru_cache(maxsize=200_000)
def _domain_resolves(domain: str) -> bool:
    try:                                        # bounded dnspython A-lookup when available
        import dns.resolver  # noqa: F401
        try:
            return bool(_dns_resolver().resolve(domain, "A"))
        except Exception:
            return False
    except ImportError:                         # stdlib fallback (can block on dead domains)
        import socket
        try:
            socket.getaddrinfo(domain, None)
            return True
        except Exception:
            return False


@functools.lru_cache(maxsize=200_000)
def _domain_has_mx(domain: str):
    """True/False if the domain has an MX record — the real 'accepts mail' signal. None when
    dnspython isn't installed (pip install 'pith[email]'); caller falls back to domain_resolves."""
    try:
        import dns.resolver  # noqa: F401
    except ImportError:
        return None
    try:
        return len(_dns_resolver().resolve(domain, "MX")) > 0
    except Exception:
        return False


def verify_email(email: str, check_domain: bool = False, check_mx: bool = False) -> dict:
    """Deterministic email quality signals — no SMTP probe, no external API, no LLM.
    Reports: valid_syntax, is_role (generic mailbox), is_disposable (throwaway domain),
    has_alias (plus-tag). `check_domain=True` adds a stdlib DNS resolve (catches dead/typo
    domains — the main rot in a stale list). `check_mx=True` adds an MX-record lookup (the real
    'accepts mail' deliverability signal; needs `pith[email]` → dnspython, else has_mx=None).
    Both are cached per domain. SMTP verification is deliberately omitted — it's unreliable
    (catch-all/greylisting) and risks sender reputation."""
    email = (email or "").strip().lower()
    if not _email_syntax_ok(email):
        return {"email": email, "valid_syntax": False}
    local, domain = email.rsplit("@", 1)
    base = local.split("+", 1)[0]
    # ISP subdomains like foo.rr.com / smtp.comcast.net -> treat by their registrable tail
    freemail = domain in _FREEMAIL or any(domain.endswith("." + f) for f in _FREEMAIL)
    out = {"email": email, "valid_syntax": True, "domain": domain,
           "is_role": base in _ROLE_LOCALS, "is_disposable": domain in _disposable(),
           "is_freemail": freemail, "has_alias": "+" in local}
    if check_domain:
        out["domain_resolves"] = _domain_resolves(domain)
    if check_mx:
        out["has_mx"] = _domain_has_mx(domain)
    return out


def _email_label(e: str) -> dict:
    """Domain-independent email signals available at page level (role/freemail). The full
    owner/person/company typing needs the business domain — that's a contact-aggregation job."""
    local, _, domain = e.lower().partition("@")
    return {"role": local.split("+", 1)[0] in _ROLE_LOCALS,
            "freemail": domain in _FREEMAIL or any(domain.endswith("." + f) for f in _FREEMAIL)}


def enrich(markdown: str, html: str, source_url: str = "") -> dict:
    """Everything deterministic, in one call. markdown feeds contact scan (clean text);
    html feeds structured/meta (needs the raw tags). `source_url` stamps provenance onto the
    returned `facts` (evidence model) — every datum knows which page + method produced it."""
    from .evidence import Source, aggregate
    src = (markdown or "") + "\n" + (html or "")
    st = structured(html)

    # ONE extraction pass -> provenance observations -> facts. The legacy lists are derived
    # from facts, so there's a single source of truth (no double extraction).
    def _s(method):
        return Source(source_url, method)
    obs = []
    obs += [(e, "email", _s("text"), _email_label(e)) for e in emails(src) if not _junk_email(e)]
    obs += [(e, "email", _s("cfemail"), _email_label(e)) for e in cfemails(html) if not _junk_email(e)]
    obs += [(e, "email", _s("atdot"), _email_label(e)) for e in atdot_emails(src) if not _junk_email(e)]
    obs += [(p, "phone", _s("text"), {}) for p in phones(html)]
    obs += [(s, "social", _s("text"), {}) for s in socials(src)]
    obs += [(a, "address", _s("schema.org"), {}) for a in addresses(html)]
    for e in st:                               # schema.org contact — but only the PAGE'S OWN
        if e.get("rel") in _THIRD_PARTY_REL:   # an author's/publisher's contact isn't the page's
            continue                           # (they stay in structured() — attribution, not hiding)
        v = e.get("email")
        if isinstance(v, str):
            obs += [(x, "email", _s("schema.org"), _email_label(x)) for x in emails(v) if not _junk_email(x)]
        t = e.get("telephone")
        if isinstance(t, (str, int)):
            obs += [(p, "phone", _s("schema.org"), {}) for p in phones(str(t))]
        sa = e.get("sameAs")
        if sa:
            obs += [(str(u), "social", _s("schema.org"), {}) for u in (sa if isinstance(sa, list) else [sa]) if _is_profile(str(u))]
    mt = meta(html)                            # fold OG/Facebook contact tags — free, previously dropped
    m_em, m_ph, m_addr = _meta_contact(mt)
    obs += [(e, "email", _s("og"), _email_label(e)) for x in m_em for e in emails(x) if not _junk_email(e)]
    obs += [(p, "phone", _s("og"), {}) for x in m_ph for p in phones(x)]
    if len(m_addr) > 8:
        obs.append((m_addr, "address", _s("og"), {}))
    facts = aggregate(obs)

    def _vals(kind):
        return sorted({f.value for f in facts if f.kind == kind})
    return {
        "emails": _vals("email"),
        "phones": _vals("phone"),
        "socials": _vals("social"),
        "addresses": _vals("address"),
        "structured": st,
        "meta": mt,
        "facts": facts,                        # evidence model: value + sources(url,method) + corroboration
    }


def _meta_contact(mt: dict) -> tuple[list, list, str]:
    """Contact fields OpenGraph/Facebook 'business'/'place' tags publish for free — and that the
    old 6-key meta allowlist dropped: business:contact_data:* and og:email/og:phone_number/address."""
    def g(*ks):
        return next((mt[k] for k in ks if mt.get(k)), "")
    em = g("business:contact_data:email", "og:email")
    ph = g("business:contact_data:phone_number", "og:phone_number")
    parts = [g("business:contact_data:street_address", "og:street_address"),
             g("business:contact_data:locality", "og:locality"),
             g("business:contact_data:region", "og:region"),
             g("business:contact_data:postal_code", "og:postal-code", "og:postal_code")]
    return ([em] if em else []), ([ph] if ph else []), ", ".join(p for p in parts if p)
