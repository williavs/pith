"""pith CLI.

Single URL:   pith <url> [--full] [--js]
A list:       pith --from companies.csv [--format md|json|table] [--workers N]

The list file is one target per line: a bare URL, or a label+URL pair (csv, either
order — the http field is the URL). '#' lines and blanks are skipped.
"""
import argparse
import csv
import json
import logging
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

from .core import Extractor, Result, _needs_browser, _BROWSER_MAX_CONCURRENCY

log = logging.getLogger("pith")


class _JsonFmt(logging.Formatter):
    """One compact JSON object per log record: the message is the `event`, any structured
    `extra=` fields ride alongside. No deps — stdlib logging + json."""
    _STD = set(logging.makeLogRecord({}).__dict__) | {"taskName", "message"}

    def format(self, rec):
        d = {"event": rec.getMessage()}
        for k, v in rec.__dict__.items():
            if k not in self._STD and k not in ("msg", "args"):
                d[k] = v
        return json.dumps(d, default=str)


def _enable_trace():
    """--verbose: stream every pipeline/network step as NDJSON on stderr (results stay on
    stdout). Surfaces pith's tier/timing/concurrency events plus scrapling's network logs."""
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(_JsonFmt())
    for name, lvl in (("pith", logging.DEBUG), ("scrapling", logging.INFO)):
        lg = logging.getLogger(name)
        lg.handlers[:] = [h]
        lg.setLevel(lvl)
        lg.propagate = False


def read_sitemap(url: str, match: str | None = None, limit: int | None = None) -> list[tuple[str | None, str]]:
    """Gather a whole doc site: fetch sitemap.xml, return its <loc> URLs as (None, url) targets.
    `match` keeps only locs containing that substring (e.g. '/router/' for one section).
    Follows a <sitemapindex> one level deep. `limit` caps the result (and warns on the cap)."""
    def fetch(u: str) -> str:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 pith"})
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

    def locs(xml: str) -> list[str]:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)

    xml = fetch(url)
    found = locs(xml)
    # a sitemap index lists child sitemaps, not pages — recurse one level
    if "<sitemapindex" in xml:
        pages: list[str] = []
        for child in found:
            try:
                pages.extend(locs(fetch(child)))
            except Exception:  # ponytail: one bad child sitemap shouldn't sink the crawl
                continue
        found = pages
    if match:
        found = [u for u in found if match in u]
    seen: set[str] = set()
    uniq = [u for u in found if not (u in seen or seen.add(u))]
    if limit and len(uniq) > limit:
        print(f"sitemap: {len(uniq)} urls, capping to --limit {limit}", file=sys.stderr)
        uniq = uniq[:limit]
    return [(None, u) for u in uniq]


# GTM-relevant sections: where decision-maker signal lives on a company site.
_SECTIONS = ("about", "contact", "team", "leadership", "people", "our-team",
             "company", "management", "founders", "staff", "careers", "jobs")


def score_relevance(query: str, url: str, snippet: str = "") -> int:
    """Buyer-signal relevance of a candidate, pre-fetch: how many query tokens appear in the
    URL + its search/anchor snippet. The gate's job is identity matching (is this about THIS
    target), which is lexical — and this beat a 270MB semantic embedder 1.00 vs 0.83 on the
    labeled dossier set (benchmarks/2026-06-30-gate-scorer.md). Generic, deterministic, no
    hardcoded priors, no model. Feed a snippet when you have one — that's where the lift is."""
    toks = {t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2}
    hay = (url + " " + snippet).lower()
    return sum(t in hay for t in toks)


def gate(targets, query: str, budget: int | None = None, snippets: dict | None = None):
    """Spend the fetch budget on the highest-signal candidates: rank (label,url) targets by
    score_relevance desc, keep the top `budget`. Stable for ties (preserves input order)."""
    snippets = snippets or {}
    ranked = sorted(targets, key=lambda t: score_relevance(query, t[1], snippets.get(t[1], "")),
                    reverse=True)
    return ranked[:budget] if budget else ranked


# --- GTM company enrichment: bare company list -> structured rows a rep can act on ---

# Multi-label public suffixes where the registrable domain is the last THREE labels, not two
# (acme.co.uk -> acme.co.uk, not co.uk). A curated set of the common ccTLD second levels — not
# the full Public Suffix List, but it covers the ccTLDs a GTM/OSINT user actually meets.
# ponytail: add tldextract (bundled PSL) if an exotic suffix shows up in real data.
_MULTI_SUFFIX = frozenset({
    "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk", "ltd.uk", "plc.uk", "net.uk", "sch.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au", "asn.au",
    "co.nz", "net.nz", "org.nz", "govt.nz", "ac.nz", "geek.nz",
    "co.za", "org.za", "net.za", "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp", "co.kr", "or.kr",
    "com.br", "net.br", "org.br", "com.mx", "com.ar", "com.co", "com.pe", "com.ve",
    "co.in", "net.in", "org.in", "firm.in", "gen.in", "ind.in", "com.sg", "com.hk", "com.tw",
    "com.cn", "net.cn", "org.cn", "gov.cn", "co.id", "com.my", "com.ph", "co.th", "in.th",
    "com.vn", "com.ua", "co.ke", "co.ug", "com.ng", "co.il", "com.tr", "gen.tr", "com.pk",
    "com.sa", "com.eg", "com.gr", "com.cy", "co.at", "or.at",
})


def _registrable(url: str) -> str:
    from urllib.parse import urlsplit
    host = urlsplit(url if "//" in url else "//" + url).netloc.lower().split(":")[0].strip(".")
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_SUFFIX:
        return ".".join(parts[-3:])          # acme.co.uk, not co.uk
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _name_toks(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) > 2]


def _company_social(socials, name: str, host_key: str):
    """Pick the company's own profile on a platform: the one whose handle matches the company
    name. Returns None rather than guess — avoids the personal-account false positive
    (github.com/1rgs for 'Ramp')."""
    toks = _name_toks(name)
    for s in socials:
        if host_key not in s.lower():
            continue
        handle = s.rstrip("/").rsplit("/", 1)[-1].lower()
        if any(t in handle or handle in t for t in toks):
            return s
    return None


def _company_emails(emails, website: str) -> list[str]:
    """Keep only emails on the company's own domain — a company-domain address is a real
    contact; an off-domain one (kevin@encom.com on linear.app) is demo/third-party noise."""
    dom = _registrable(website)
    # exact domain or a true subdomain (dot boundary) — NOT a suffix match, which would let
    # notacme.co.uk pass for acme.co.uk.
    return [e for e in emails
            if (d := e.split("@")[-1].lower()) == dom or d.endswith("." + dom)]


def enrich_company(name: str, website: str, workers: int = 4) -> dict:
    """A GTM-ready firmographic row, composed transparently from contact_evidence + recipes
    (not an opaque wrapper): company-matched socials, on-domain emails (typed, so functional
    mailboxes are visible), careers signal, and tech grade. The raw evidence is one call away
    via contact_evidence(website)."""
    ev = contact_evidence(website, workers=workers)
    socials = {f.value for f in ev["facts"] if f.kind == "social"}
    # company emails = on-domain, excluding role/functional if the caller wants people (here: keep all typed)
    emails = [f.value for f in ev["facts"] if f.kind == "email"
              and f.labels.get("email_type") in ("owner", "person", "role", "functional")]
    urls = ev["coverage"].ok
    from .core import _fetch_static
    from .techstack import analyze
    try:                                         # tech/modernness column (one homepage fetch)
        a = analyze(_fetch_static(website), website)
    except Exception:
        a = {"modernness_grade": "?", "builder": "?", "hosted_builder": None}
    return {
        "company": name, "website": website, "pages": len(urls),
        "linkedin": _company_social(socials, name, "linkedin.com/company"),
        "github": _company_social(socials, name, "github.com"),
        "twitter": _company_social(socials, name, "twitter.com") or _company_social(socials, name, "x.com"),
        "emails": sorted(emails),
        "careers": any("career" in u.lower() or "/job" in u.lower() for u in urls),
        "grade": a.get("modernness_grade"), "builder": a.get("builder"), "hosted": a.get("hosted_builder"),
    }



def _whois_registrant(domain: str) -> dict:
    """Registrant email/phone/name from WHOIS, with privacy-proxy records dropped (their
    phone is the proxy's, not the owner's). Real for small biz that never enabled privacy."""
    import subprocess
    try:
        out = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return {}
    proxy = ("domains by proxy", "registration private", "privacy", "redacted", "whoisguard",
             "withheld", "/whois", "contactdomainowner", "not disclosed", "perfect privacy")
    got = {}
    for line in out.splitlines():
        m = re.match(r"\s*Registrant (Email|Phone|Name|Organization)\s*:\s*(.+)", line, re.I)
        if m and m.group(1).lower() not in got:
            got[m.group(1).lower()] = m.group(2).strip()
    if any(p in str(v).lower() for v in got.values() for p in proxy):
        return {}
    return {k: v for k, v in got.items() if v}


def _name_like(local: str) -> bool:
    """A local part that looks like a real person: firstname.lastname / first_last (two short
    alpha tokens joined by . or _). A hyphen is NOT a name join — it's team mailboxes
    (security-internal, security-reports), which must stay 'functional', not 'person'."""
    return bool(re.match(r"^[a-z]{2,12}[._][a-z]{2,12}$", local.split("+", 1)[0]))


def _email_type_scoped(email: str, domain: str) -> str:
    """Dot-boundary domain match + a 'functional' bucket for on-domain mailboxes that are
    neither a known role nor a real name (accommodations@) — so a recipe preferring people
    doesn't grab them. Types: owner | person | role | functional | external | drop."""
    from .extract import verify_email
    v = verify_email(email)
    if not v["valid_syntax"] or v["is_disposable"]:
        return "drop"
    if v["is_freemail"]:
        return "owner"                                   # freemail on a business = owner-operator
    local = email.split("@")[0].lower()
    d = email.split("@")[-1].lower()
    if d == domain or d.endswith("." + domain):
        if v["is_role"]:
            return "role"
        return "person" if _name_like(local) else "functional"
    return "external"


def contact_evidence(website: str, workers: int = 4) -> dict:
    """EVIDENCE (not answers) for a business's public contact footprint. Crawls key pages,
    unions every extracted Fact across them (corroboration = distinct source pages), types
    emails by the business domain, folds in the WHOIS registrant as another source, and reports
    coverage (what was crawled / what failed). Returns Fact objects + Coverage — NO 'primary'
    pick, no scalar. Apply pith.recipes (owner_email, rank_phones) with your intent on top."""
    from .evidence import Source, Coverage, aggregate
    domain = _registrable(website)
    ex = Extractor()
    try:
        targets = crawl_site(website, limit=8)
    except Exception:
        targets = [(None, website)]
    urls = [u for _, u in targets]
    out = ex.extract(urls, concurrency=workers)
    cov = Coverage(checked=urls, ok=[r.url for r in out.results],
                   failed=[{"url": e.get("url"), "error": str(e.get("error", ""))[:80]}
                           for e in (out.errors or [])])
    # union every page's facts -> cross-page corroboration (distinct source URLs)
    obs = [(f.value, f.kind, s, f.labels) for r in out.results for f in r.facts for s in f.sources]
    for r in out.results:                                 # schema.org Person -> a named contact
        for e in r.structured:
            types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
            if "Person" in types and e.get("name"):
                obs.append((str(e["name"]), "name", Source(r.url, "schema.org"),
                            {"title": e.get("jobTitle", "")}))
    # WHOIS registrant contact = another independent source
    whois = _whois_registrant(domain)
    if whois.get("email"):
        obs.append((whois["email"], "email", Source(f"whois:{domain}", "whois"), {}))
    if whois.get("phone"):
        from .extract import _canon_phone
        obs.append((_canon_phone(whois["phone"]) or whois["phone"], "phone", Source(f"whois:{domain}", "whois"), {}))
    facts = aggregate(obs)
    for f in facts:                                       # domain-aware email typing (transparent label)
        if f.kind == "email":
            f.labels["email_type"] = _email_type_scoped(f.value, domain)
    facts = [f for f in facts if not (f.kind == "email" and f.labels.get("email_type") == "drop")]
    return {"domain": domain, "facts": facts, "coverage": cov, "whois": whois}


def _facts_of(evidence: dict, kind: str):
    return [f for f in evidence["facts"] if f.kind == kind]


def render_contact(c: dict, fmt: str) -> str:
    """Render contact_evidence. Shows every fact with its corroboration + type + coverage —
    no 'primary' pick (that's the caller's, via pith.recipes)."""
    if fmt == "json":
        return json.dumps({"domain": c["domain"],
                           "facts": [f.as_dict() for f in c["facts"]],
                           "coverage": c["coverage"].as_dict(), "whois": c["whois"]}, indent=2)
    cov = c["coverage"]
    out = [f"CONTACT EVIDENCE: {c['domain']}  ({len(cov.ok)}/{len(cov.checked)} pages ok)"]
    people = _facts_of(c, "name")
    if people:
        out.append("people:")
        out += [f"  {f.value}" + (f" — {f.labels['title']}" if f.labels.get("title") else "") for f in people]
    out.append("emails:")
    out += [f"  {f.value:34} [{f.labels.get('email_type','?')}] x{f.corroboration}" for f in _facts_of(c, "email")] or ["  (none found)"]
    out.append("phones:")
    out += [f"  {f.value:18} x{f.corroboration} {f.methods}" for f in _facts_of(c, "phone")] or ["  (none published)"]
    socials = _facts_of(c, "social")
    out.append(f"socials: {', '.join(f.value for f in socials[:6]) or '(none)'}")
    if cov.inconclusive or cov.failed:
        out.append(f"coverage gaps: {len(cov.failed)} failed, {len(cov.inconclusive)} inconclusive")
    return "\n".join(out)


# directories/aggregators/social — not the business's own site; skip when prospecting.
_AGGREGATORS = ("yelp.", "facebook.", "angi.", "angieslist.", "bbb.org", "yellowpages.",
                "google.", "indeed.", "reddit.", "thumbtack.", "mapquest.", "linkedin.",
                "instagram.", "houzz.", "nextdoor.", "glassdoor.", "tripadvisor.", "amazon.",
                "wikipedia.", "youtube.", "pinterest.", "manta.", "chamberofcommerce.")


def _business_urls(results, limit):
    """From search results, keep one URL per real business domain (drop aggregators/dirs)."""
    from urllib.parse import urlsplit
    urls, seen = [], set()
    for r in results:
        u = (r.get("url") or "").strip()
        dom = urlsplit(u).netloc.lower()
        if not dom or dom in seen or any(a in dom for a in _AGGREGATORS):
            continue
        seen.add(dom)
        urls.append(u)
        if len(urls) >= limit:
            break
    return urls


def _parse_yp(html: str, limit: int) -> list[dict]:
    """Parse YellowPages search results -> business records (name, phone, address, website)."""
    import html as _h
    out = []
    for card in re.split(r'<div class="info">', html or "")[1:]:  # 1 card per business
        name = re.search(r'class="business-name"[^>]*>([^<]+)', card)
        if not name:
            continue
        phone = re.search(r'class="phone[s]?[^"]*"[^>]*>([^<]{7,20})', card)
        adr = re.search(r'class="adr"[^>]*>([^<]+)', card)
        if not adr:
            st = re.search(r'class="street-address"[^>]*>([^<]+)', card)
            lo = re.search(r'class="locality"[^>]*>([^<]+)', card)
            addr = f"{st.group(1)} {lo.group(1)}" if st and lo else ""
        else:
            addr = adr.group(1)
        site = re.search(r'href="(https?://(?!www\.yellowpages\.com)[^"]+)"[^>]*>\s*Website', card)
        out.append({
            "name": _h.unescape(name.group(1).strip()),
            "phone": phone.group(1).strip() if phone else "",
            "address": _h.unescape(addr.strip()),
            "website": site.group(1) if site else "",
        })
        if len(out) >= limit:
            break
    return out


def _fetch_directory_page(url: str) -> str:
    from .core import _fetch_impersonate, _fetch_static, _fetch_js
    for fetch in (_fetch_impersonate, _fetch_static, _fetch_js):  # YP rate-limits plain HTTP
        try:
            html = fetch(url)
            if 'class="business-name"' in html:
                return html
        except Exception:
            continue
    return ""


def directory_search(category: str, location: str, limit: int = 30) -> list[dict]:
    """Category+geo -> a structured business list (name/phone/address/website), paginated,
    from YellowPages AND SuperPages (both Thryv, same markup). Two sources fill each other's
    gaps and cover for rate-limiting; results deduped by name + phone digits. Walks pages
    until `limit` reached, so you can pull hundreds of local businesses per category+geo."""
    from urllib.parse import quote_plus
    ct, loc = quote_plus(category), quote_plus(location)
    sources = [
        f"https://www.yellowpages.com/search?search_terms={ct}&geo_location_terms={loc}",
        f"https://www.superpages.com/search?search_terms={ct}&geo_location_terms={loc}",
    ]
    rows, seen = [], set()
    for base in sources:
        page = 1
        while len(rows) < limit and page <= 40:            # 40-page ceiling per source
            html = _fetch_directory_page(base + f"&page={page}")
            if not html:
                break
            new = 0
            for r in _parse_yp(html, 10 ** 6):
                k = (r["name"].lower(), re.sub(r"\D", "", r["phone"]))  # dedup by name + phone digits
                if not r["name"] or k in seen:
                    continue
                seen.add(k)
                rows.append(r)
                new += 1
                if len(rows) >= limit:
                    break
            if new == 0:                                    # end of listings for this source
                break
            print(f"[directory] {base.split('//')[1].split('.')[1]} page {page}: {len(rows)} total",
                  file=sys.stderr, flush=True)
            page += 1
        if len(rows) >= limit:
            break
    return rows[:limit]


def render_directory(rows, fmt):
    if fmt == "json":
        return json.dumps(rows, indent=2)
    if fmt == "csv":
        import csv as _csv
        import io
        buf = io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=["name", "phone", "website", "address"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().rstrip()
    out = [f"{'business':32} {'phone':16} website"]
    for r in rows:
        out.append(f"{r['name'][:32]:32} {r['phone']:16} {r['website'][:40] or '(none)'}")
    out.append(f"\n{len(rows)} businesses · {sum(1 for r in rows if r['website'])} with a website")
    return "\n".join(out)


def searx_urls(query, limit=10):
    """Search a SearXNG instance -> business homepage URLs. Instance from $PITH_SEARX_URL."""
    import os
    from urllib.parse import urlencode
    base = os.environ.get("PITH_SEARX_URL")
    if not base:
        raise SystemExit("--prospect needs a SearXNG instance: set PITH_SEARX_URL=http://host:port")
    url = base.rstrip("/") + "/search?" + urlencode({"q": query, "format": "json"})
    data = json.load(urllib.request.urlopen(url, timeout=25))
    return _business_urls(data.get("results", []), limit)


def prospect(query, limit=10, workers=4):
    """One category+geo search -> a lead list, each with contact EVIDENCE. GTM top of funnel."""
    leads = []
    for url in searx_urls(query, limit):
        print(f"[prospect] {url}", file=sys.stderr, flush=True)
        leads.append(contact_evidence(url, workers=workers))
    return leads


def _best_contact(lead):
    """A default pick over the evidence, via recipes — the app can pick differently."""
    from . import recipes
    oe = recipes.owner_email(lead["facts"], prefer=("owner", "person", "role", "functional"))
    if oe:
        return oe.value, oe.labels.get("email_type", "email")
    ph = recipes.rank_phones(lead["facts"])
    if ph:
        return ph[0].value, "phone"
    return "-", "-"


def render_leads(leads, fmt):
    from . import recipes
    def phone(l):
        ph = recipes.rank_phones(l["facts"])
        return ph[0].value if ph else ""
    def socials(l):
        return [f.value for f in l["facts"] if f.kind == "social"]
    def reachable(l):
        return any(f.kind in ("email", "phone") for f in l["facts"])
    if fmt == "json":
        return json.dumps([{"domain": l["domain"], "facts": [f.as_dict() for f in l["facts"]],
                            "coverage": l["coverage"].as_dict()} for l in leads], indent=2)
    if fmt == "csv":
        import csv as _csv
        import io
        buf = io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["business", "best_contact", "contact_type", "phone", "socials"])
        for l in leads:
            best, typ = _best_contact(l)
            w.writerow([l["domain"], best, typ, phone(l), ";".join(socials(l)[:3])])
        return buf.getvalue().rstrip()
    out = [f"{'business':30} {'best contact':34} {'type':8} phone"]
    for l in leads:
        best, typ = _best_contact(l)
        out.append(f"{l['domain'][:30]:30} {best[:34]:34} {typ:8} {phone(l) or '-'}")
    out.append(f"\n{len(leads)} leads · {sum(1 for l in leads if reachable(l))} with contact")
    return "\n".join(out)


def render_profiles(hits, fmt, verified):
    if fmt == "json":
        return json.dumps(hits, indent=2)
    out = []
    for h in hits:
        v = (f"  [{h['verdict']} {int(h.get('confidence', 0) * 100)}% {'+'.join(h.get('signals', [])) or 'weak'}]"
             if verified else "")
        out.append(f"  [{h['kind'][:4]}/{h['value']:4}] {h['site']:14} {h['url']}{v}")
    n = len(hits)
    tail = (" (verified as the target)" if verified
            else " (existence only — add --verify-name / --verify-company to confirm identity)")
    out.append(f"\n{n} profile{'s' if n != 1 else ''}{tail}")
    return "\n".join(out)


# --- website tech + modernness intel (for selling website services) ---

def _domain_age_years(domain: str):
    import subprocess
    try:
        out = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return None
    m = re.search(r"(?:Creation Date|Registered on|Registration Time|created)\D{0,4}(\d{4})", out, re.I)
    return (2026 - int(m.group(1))) if m else None


def website_intel(url: str) -> dict:
    """Homepage -> tech stack + modernness grade + domain age. For finding dated sites to pitch."""
    from .core import _fetch_static, _fetch_js, _needs_browser
    from .techstack import analyze
    try:
        html = _fetch_js(url) if _needs_browser(url) else _fetch_static(url)
    except Exception:
        html = ""
    a = analyze(html, url)
    a["domain"] = _registrable(url)
    a["domain_age_years"] = _domain_age_years(a["domain"])
    return a


def render_intel(a: dict, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(a, indent=2)
    age = f"{a['domain_age_years']} yrs" if a["domain_age_years"] else "?"
    return "\n".join([
        f"SITE: {a['domain']}",
        f"  grade:      {a['modernness_grade']}  ({a['modernness_score']}/100)",
        f"  builder:    {a['builder']}" + ("   (paying a hosted service — switch pitch)" if a["hosted_builder"] else ""),
        f"  framework:  {a['framework'] or '-'}",
        f"  responsive: {a['responsive']}    https: {a['https']}",
        f"  domain age: {age}    copyright: {a['copyright_year'] or '?'}",
        f"  dated:      {', '.join(a['dated_signals']) or 'none'}",
    ])


def render_enrich(rows, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(rows, indent=2)
    if fmt == "csv":
        import csv as _csv
        import io
        cols = ["company", "website", "grade", "builder", "hosted", "pages", "linkedin", "github", "twitter", "careers", "emails"]
        buf = io.StringIO()
        w = _csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, "emails": ";".join(r["emails"])})
        return buf.getvalue().rstrip()
    # table
    out = [f"{'company':14} {'grd':3} {'builder':16} {'careers':7} {'linkedin':28} emails"]
    for r in rows:
        out.append(f"{r['company'][:14]:14} {(r.get('grade') or '?'):3} {(r.get('builder') or '?')[:16]:16} "
                   f"{'yes' if r['careers'] else '-':7} {(r['linkedin'] or '-')[:28]:28} {','.join(r['emails'])[:34]}")
    return "\n".join(out)


def _section_links(seed: str, html: str, sections, limit: int) -> list[tuple[str | None, str]]:
    """Pure: from a homepage's HTML, keep same-domain links whose path hits a section.
    Seed first, then matches in document order, deduped, capped. (Tested offline.)"""
    from urllib.parse import urljoin, urlsplit
    host = urlsplit(seed).netloc
    out, seen = [(None, seed)], {seed}
    for href in re.findall(r'href=["\']([^"\']+)', html):
        u = urljoin(seed, href).split("#")[0]
        sp = urlsplit(u)
        if sp.netloc == host and any(s in sp.path.lower() for s in sections) and u not in seen:
            seen.add(u)
            out.append((None, u))
            if len(out) >= limit:
                break
    return out


def crawl_site(seed: str, sections=_SECTIONS, limit: int = 25) -> list[tuple[str | None, str]]:
    """Strategic crawl: fetch a homepage, follow one level of same-domain links into the
    high-value sections (about/contact/team/...). One level — nav links cover the GTM
    sections, and walled pages cost ~4-5s each so coverage is the wrong goal anyway.
    ponytail: one level; recurse if a real site buries its team page deeper than nav."""
    from .core import _fetch_static
    html = _fetch_static(seed)   # SSRF-guarded + gzip-aware (raw urllib.urlopen was neither)
    return _section_links(seed, html, sections, limit)


def read_targets(path: str) -> list[tuple[str | None, str]]:
    """Parse a URL-list file into (label, url) pairs. Bare URL -> label None.
    Handles plain .txt (one URL per line) and .csv (label,url or url,label)."""
    targets: list[tuple[str | None, str]] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            cells = [c.strip() for c in row if c.strip()]
            if not cells or cells[0].startswith("#"):
                continue
            url = next((c for c in cells if c.startswith(("http://", "https://"))), None)
            if not url:  # ponytail: skip junk lines, don't sink the batch
                continue
            label = next((c for c in cells if c != url), None)
            targets.append((label, url))
    return targets


def run_batch(ex, targets, *, full, render_js, workers, verbose=False):
    """Drive the extractor over targets, one extract() per URL so we can show progress
    and parallelize. Returns (label, url, Result | error-dict) rows in input order."""
    total = len(targets)
    # tier-safety: a walled URL spawns a stealth browser (~hundreds of MB). If any target is
    # walled, cap concurrency so a big --workers can't OOM the box (browser knee is ~3 anyway,
    # measured in walled-physics.md). Pure open-web batches keep full --workers.
    if workers > _BROWSER_MAX_CONCURRENCY and any(_needs_browser(u) for _, u in targets):
        workers = _BROWSER_MAX_CONCURRENCY
    log.info("batch_start", extra={"n": total, "workers": workers})

    def one(item):
        i, (label, url) = item
        if verbose:
            log.info("fetch_start", extra={"i": i, "n": total, "url": url, "label": label})
        else:
            print(f"[{i}/{total}] {label or url}", file=sys.stderr, flush=True)
        out = ex.extract(urls=[url], full_content=full, render_js=render_js)
        return (label, url, out.results[0] if out.results else out.errors[0])

    items = list(enumerate(targets, 1))
    if workers > 1:
        # ponytail: thread the fetches; the stealth browser launches per-call so it's
        # thread-safe enough here. Drop --workers to 1 if a site gets flaky under load.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(one, items))
    else:
        rows = [one(it) for it in items]
    ok = sum(1 for _, _, r in rows if isinstance(r, Result))
    log.info("batch_done", extra={"n": total, "ok": ok, "errors": total - ok})
    return rows


def render(rows, fmt: str) -> str:
    ok = [(l, u, r) for l, u, r in rows if isinstance(r, Result)]
    err = [(l, u, r) for l, u, r in rows if not isinstance(r, Result)]

    if fmt == "json":
        return json.dumps({
            "results": [{"label": l, **asdict(r)} for l, u, r in ok],
            "errors": [{"label": l, "url": u, "error": r.get("error")} for l, u, r in err],
        }, indent=2)

    if fmt == "table":
        out = [f"{'STATUS':<7} {'BYTES':>7}  TARGET"]
        for l, u, r in rows:
            if isinstance(r, Result):
                n = len(r.full_content or (r.excerpts[0] if r.excerpts else ""))
                out.append(f"{'ok':<7} {n:>7}  {l or u}")
            else:
                out.append(f"{'ERROR':<7} {'-':>7}  {l or u}: {str(r.get('error'))[:50]}")
        out.append(f"\n{len(ok)} ok, {len(err)} errors")
        return "\n".join(out)

    # markdown (default)
    out = []
    for l, u, r in ok:
        out.append(f"## {l}" if l else f"## {u}")
        if r.title:
            out.append(f"# {r.title}")
        if r.publish_date:
            out.append(f"_{r.publish_date}_")
        out.append("")
        out.extend(r.excerpts)
        out.append("")
    for l, u, r in err:
        out.append(f"## {l or u}\n[error] {r.get('error')}\n")
    out.append(f"---\n_{len(ok)} ok, {len(err)} errors_")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(prog="pith", description="URL -> clean LLM-ready markdown (free).")
    ap.add_argument("url", nargs="?", help="a single URL (omit when using --from)")
    ap.add_argument("--from", dest="from_file", metavar="FILE", help="batch: read URLs from a list file (txt or csv)")
    ap.add_argument("--sitemap", metavar="URL", help="batch: crawl a sitemap.xml and gather every page (filter with --match)")
    ap.add_argument("--crawl", metavar="URL", help="batch: from a homepage, follow links into about/contact/team/... sections")
    ap.add_argument("--match", metavar="SUBSTR", help="with --sitemap: keep only URLs containing this substring")
    ap.add_argument("--limit", type=int, default=25, help="cap pages gathered by --sitemap/--crawl (default 25)")
    ap.add_argument("--directory", metavar="CATEGORY", help="GTM: build a business list from YellowPages (use with --geo, e.g. --directory plumber --geo 'Columbus, OH')")
    ap.add_argument("--geo", metavar="LOCATION", help="with --directory: city, state (e.g. 'Columbus, OH')")
    ap.add_argument("--prospect", metavar="QUERY", help="GTM: search a category+geo (needs $PITH_SEARX_URL) -> a lead list, each with dug owner contact")
    ap.add_argument("--intel", metavar="URL", help="GTM: website tech stack + modernness grade + domain age (find dated sites to sell services to)")
    ap.add_argument("--profiles", metavar="HANDLE", help="OSINT: find a person's public profiles across the web (add --verify-* to confirm identity)")
    ap.add_argument("--verify-name", metavar="NAME", help="with --profiles: corroborate each profile against this person's name")
    ap.add_argument("--verify-company", metavar="DOMAIN", help="with --profiles: corroborate against this company domain")
    ap.add_argument("--anchor", metavar="URL", action="append", help="with --profiles: a known-good profile URL for the person (repeatable; a backlink to it is decisive)")
    ap.add_argument("--email", metavar="ADDR", action="append", help="with --profiles: a known email for the person (repeatable)")
    ap.add_argument("--persona", choices=["technical", "creative", "founder", "exec", "default"], help="with --profiles: which value sites to hit for this buyer type")
    ap.add_argument("--all-sites", action="store_true", help="with --profiles: check all ~480 sites (the long tail), not just the curated GTM subset")
    ap.add_argument("--include-review", action="store_true", help="with --profiles: also surface REVIEW (single-signal) matches, not just ACCEPT")
    ap.add_argument("--find", metavar="URL", help="GTM: dig a business's public owner contact (ranked emails, phones, socials, WHOIS)")
    ap.add_argument("--enrich", metavar="FILE", help="GTM: read a company list (name,website csv) and output an enriched row per company (socials, emails, careers)")
    ap.add_argument("--about", metavar="QUERY", help="batch: rank candidates by relevance to this (e.g. a target name+company) and fetch the most relevant first")
    ap.add_argument("--budget", type=int, help="with --about: fetch only the top-N most relevant candidates (skip the rest — saves the 4-5s/page walled-fetch cost)")
    ap.add_argument("--format", choices=["md", "json", "table", "csv"], default="md", help="output format (csv/json for --enrich; default md)")
    ap.add_argument("--workers", type=int, default=1, help="batch: parallel fetches (default 1)")
    ap.add_argument("--full", action="store_true", help="include full page markdown")
    ap.add_argument("--js", action="store_true", help="force a real browser (JS-rendered / bot-protected pages)")
    ap.add_argument("--verbose", "-v", action="store_true", help="stream a structured NDJSON trace of every pipeline step (tiers, timing, concurrency, network) to stderr")
    args = ap.parse_args()

    if args.verbose:
        _enable_trace()
    render_js = True if args.js else "auto"
    ex = Extractor()

    if args.directory:  # GTM: YellowPages category+geo -> business list
        if not args.geo:
            ap.error("--directory needs --geo (e.g. --geo 'Columbus, OH')")
        rows = directory_search(args.directory, args.geo, limit=args.limit)
        print(render_directory(rows, "table" if args.format == "md" else args.format))
        return

    if args.prospect:  # GTM: search a category+geo -> lead list with owner contact
        leads = prospect(args.prospect, limit=args.limit, workers=args.workers)
        print(render_leads(leads, "table" if args.format == "md" else args.format))
        return

    if args.intel:  # GTM: website tech + modernness intel
        print(render_intel(website_intel(args.intel), "json" if args.format == "json" else "table"))
        return

    if args.profiles:  # OSINT: public profiles across the web, identity-corroborated
        from .profiles import enumerate_profiles
        verifying = bool(args.verify_name or args.verify_company or args.anchor or args.email)
        if verifying:
            from .resolve import Target, resolve_profiles
            target = Target(name=args.verify_name or "",
                            website=("https://" + args.verify_company) if args.verify_company else "",
                            anchors=set(args.anchor or []), emails=set(args.email or []))
            hits = resolve_profiles(args.profiles, target, persona=args.persona,
                                    all_sites=args.all_sites, include_review=args.include_review)
        else:
            hits = enumerate_profiles(args.profiles, persona=args.persona, all_sites=args.all_sites)
        print(render_profiles(hits, "json" if args.format == "json" else "table", verifying))
        return

    if args.find:  # GTM: dig one business's contact EVIDENCE
        print(render_contact(contact_evidence(args.find, workers=args.workers),
                             "json" if args.format == "json" else "table"))
        return

    if args.enrich:  # GTM: company list -> enriched rows
        companies = read_targets(args.enrich)
        if not companies:
            ap.error(f"no companies found in {args.enrich}")
        rows = [enrich_company(name or url, url, workers=args.workers) for name, url in companies]
        print(render_enrich(rows, "table" if args.format == "md" else args.format))
        return

    if args.sitemap or args.crawl or args.from_file:
        if args.sitemap:
            targets = read_sitemap(args.sitemap, match=args.match, limit=args.limit)
        elif args.crawl:
            targets = crawl_site(args.crawl, limit=args.limit)
        else:
            targets = read_targets(args.from_file)
        if not targets:
            ap.error("no URLs found (check --sitemap/--match or the --from file)")
        if args.about:  # fetch-budget gate: rank by relevance, keep top --budget
            n = len(targets)
            targets = gate(targets, args.about, budget=args.budget)
            log.info("gate_ranked", extra={"candidates": n, "kept": len(targets), "budget": args.budget, "query": args.about})
            if not args.verbose:
                print(f"gate: ranked {n} candidates by '{args.about}'"
                      + (f", fetching top {args.budget}" if args.budget else ""), file=sys.stderr)
        rows = run_batch(ex, targets, full=args.full,
                         render_js=render_js, workers=args.workers, verbose=args.verbose)
        print(render(rows, args.format))
        return

    if not args.url:
        ap.error("provide a URL, or --from FILE for a list")

    out = ex.extract(urls=[args.url], full_content=args.full, render_js=render_js)
    for r in out.results:
        if r.title:
            print(f"# {r.title}")
        if r.publish_date:
            print(f"_{r.publish_date}_\n")
        for e in r.excerpts:
            print(e)
    for err in out.errors:
        print(f"[error] {err['url']}: {err['error']}")


if __name__ == "__main__":
    main()
