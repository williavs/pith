"""Keyless job-board company intelligence — hiring data is freely, publicly offered.

Most companies post through an ATS with a PUBLIC, KEYLESS board, and link it from their own
/careers page. pith DISCOVERS which board a company uses (from that page) and pulls every open
posting: headcount growth, departments, locations, seniority, specific roles — a dense, honest
signal. Covers the popular and long-tail ATSs and keeps up as new ones appear (just add a row
to _ATS). Falls back to the company's OWN careers page (schema.org JobPosting) when there's no
third-party board.

CORE = acquisition: discover the board, fetch + normalize raw postings. What they MEAN (intent,
growth, tech-stack inference) is the caller's judgment — see examples/gtm/buyer_intent.py.

    from pith.jobs import jobs_search
    j = jobs_search("Stripe", "stripe.com")   # -> {ats, token, count, postings:[{title,location,department,url,posted}]}

Keyless, deterministic, public. LinkedIn/Indeed are walled (auth/anti-bot) — out of scope; the
open ATS APIs + first-party schema cover most of the market.
"""
from __future__ import annotations

import json
import re
import urllib.request


def _get(url: str, timeout: int = 12, data: dict | None = None) -> str:
    from .core import _guard_url
    _guard_url(url)
    headers = {"User-Agent": "Mozilla/5.0 pith"}
    body = None
    if data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode()
    req = urllib.request.Request(url, headers=headers, data=body)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def _jget(url, data=None):
    return json.loads(_get(url, data=data))


# --- per-ATS normalizers: raw JSON -> [{title, location, department, url, posted}] ---
def _n_greenhouse(d):
    return [{"title": j.get("title"), "location": (j.get("location") or {}).get("name"),
             "department": ", ".join(x.get("name", "") for x in j.get("departments", [])) or None,
             "url": j.get("absolute_url"), "posted": j.get("updated_at") or j.get("first_published")}
            for j in d.get("jobs", [])]


def _n_lever(d):
    arr = d if isinstance(d, list) else d.get("data", [])
    return [{"title": j.get("text"), "location": (j.get("categories") or {}).get("location"),
             "department": (j.get("categories") or {}).get("team") or (j.get("categories") or {}).get("department"),
             "url": j.get("hostedUrl"), "posted": None} for j in arr]


def _n_ashby(d):
    return [{"title": j.get("title"), "location": j.get("location"),
             "department": j.get("department") or j.get("team"),
             "url": j.get("jobUrl") or j.get("applyUrl"), "posted": j.get("publishedDate")}
            for j in d.get("jobs", [])]


def _n_workable(d):
    arr = d.get("results") or d.get("jobs") or (d if isinstance(d, list) else [])
    return [{"title": j.get("title"), "location": ((j.get("location") or {}).get("location_str")
                                                   or (j.get("location") or {}).get("city")),
             "department": j.get("department"), "url": j.get("url") or j.get("application_url") or j.get("shortlink"),
             "posted": j.get("published_on") or j.get("created_at")} for j in arr]


def _n_recruitee(d):
    return [{"title": j.get("title"), "location": j.get("location") or j.get("city"),
             "department": j.get("department"), "url": j.get("careers_url") or j.get("careers_apply_url"),
             "posted": j.get("published_at")} for j in d.get("offers", [])]


def _n_smartrecruiters(d):
    return [{"title": j.get("name"), "location": (j.get("location") or {}).get("city"),
             "department": (j.get("department") or {}).get("label"),
             "url": j.get("ref"), "posted": j.get("releasedDate")} for j in d.get("content", [])]


def _n_breezy(d):
    arr = d if isinstance(d, list) else d.get("positions", [])
    return [{"title": j.get("name"), "location": (j.get("location") or {}).get("name"),
             "department": (j.get("department") or {}).get("name") if isinstance(j.get("department"), dict) else j.get("department"),
             "url": j.get("url"), "posted": j.get("published_date") or j.get("creation_date")} for j in arr]


def _n_recruitee2(d):  # Comeet/Personio share a shape via generic
    return _n_recruitee(d)


# name, careers-page link regex (group 1 = token), api url template, normalizer
_ATS = [
    ("greenhouse", r"(?:boards|job-boards|boards-api)\.greenhouse\.io/(?:embed/job_board\?for=|v1/boards/)?([a-z0-9][a-z0-9_-]+)",
     "https://boards-api.greenhouse.io/v1/boards/{}/jobs", _n_greenhouse),
    ("lever", r"jobs\.lever\.co/([a-z0-9][a-z0-9-]+)",
     "https://api.lever.co/v0/postings/{}?mode=json", _n_lever),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9][a-z0-9-]+)",
     "https://api.ashbyhq.com/posting-api/job-board/{}", _n_ashby),
    ("workable", r"(?:apply\.workable\.com/|([a-z0-9-]+)\.workable\.com)",
     "https://apply.workable.com/api/v3/accounts/{}/jobs", _n_workable),
    ("recruitee", r"([a-z0-9][a-z0-9-]+)\.recruitee\.com",
     "https://{}.recruitee.com/api/offers/", _n_recruitee),
    ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9][a-z0-9-]+)",
     "https://api.smartrecruiters.com/v1/companies/{}/postings", _n_smartrecruiters),
    ("breezy", r"([a-z0-9][a-z0-9-]+)\.breezy\.hr",
     "https://{}.breezy.hr/json", _n_breezy),
]

# Workday is special (POST + a {token}.{dc}.myworkdayjobs.com/{site} triple), handled separately.
_WORKDAY = re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_]+)", re.I)

_CAREERS_PATHS = ("/careers", "/careers/", "/jobs", "/careers/jobs", "/company/careers",
                  "/about/careers", "/join-us", "/work-with-us", "/company/jobs", "/en/careers")


def _try_board(tmpl, token, norm):
    try:
        return [p for p in norm(_jget(tmpl.format(token))) if p.get("title")]
    except Exception:
        return None


def _workday(html):
    m = _WORKDAY.search(html or "")
    if not m:
        return None
    token, dc, site = m.group(1), m.group(2), m.group(3)
    host = f"{token}.{dc}.myworkdayjobs.com"
    try:
        d = _jget(f"https://{host}/wday/cxs/{token}/{site}/jobs", data={"limit": 20, "offset": 0, "searchText": ""})
        return "workday", token, [{"title": j.get("title"), "location": j.get("locationsText"),
                                   "department": None, "url": f"https://{host}{j.get('externalPath', '')}",
                                   "posted": j.get("postedOn")} for j in d.get("jobPostings", []) if j.get("title")]
    except Exception:
        return None


def _safe_get(url, timeout=7):
    try:
        return _get(url, timeout=timeout)   # short: a careers page that's slow to first byte is a miss
    except Exception:
        return None


def _jobposting_from(html):
    """The company's OWN careers page — schema.org JobPosting (Google-for-Jobs SEO markup)."""
    from .extract import _JSON_LD, _walk_entities
    out = []
    for block in _JSON_LD.findall(html or ""):
        try:
            data = json.loads(block)
        except Exception:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", block))
            except Exception:
                continue
        for e, _ in _walk_entities(data):
            if not isinstance(e, dict):
                continue
            types = e.get("@type") if isinstance(e.get("@type"), list) else [e.get("@type")]
            if "JobPosting" not in types:
                continue
            loc = e.get("jobLocation")
            loc = (loc[0] if isinstance(loc, list) and loc else loc) or {}
            addr = loc.get("address") if isinstance(loc, dict) else {}
            addr = addr if isinstance(addr, dict) else {}
            out.append({"title": e.get("title"),
                        "location": addr.get("addressLocality") or addr.get("addressRegion"),
                        "department": e.get("occupationalCategory") if isinstance(e.get("occupationalCategory"), str) else None,
                        "url": e.get("url"), "posted": e.get("datePosted")})
    return [p for p in out if p.get("title")]


_EIGHTFOLD = re.compile(r"https?://([a-z0-9.-]*(?:eightfold\.ai|jobs\.[a-z0-9-]+\.(?:net|com)))/", re.I)


def _eightfold(html, domain):
    """Eightfold-powered career sites (Netflix, many enterprises) — keyless positions API."""
    hosts = set(re.findall(r"https?://([a-z0-9.-]+)/careers/", html, re.I)) | set(
        m for m in re.findall(r"https?://([a-z0-9.-]+eightfold\.ai)", html, re.I))
    hosts |= set(re.findall(r"https?://(explore\.jobs\.[a-z0-9-]+\.(?:net|com))", html, re.I))
    for host in hosts:
        try:
            d = _jget(f"https://{host}/api/apply/v2/jobs?domain={domain}&num=100&sort_by=timestamp")
            ps = d.get("positions") or d.get("jobs") or []
            out = [{"title": p.get("name") or p.get("title"), "location": p.get("location"),
                    "department": p.get("department"), "url": p.get("canonicalPositionUrl") or p.get("job_url"),
                    "posted": p.get("t_create") or p.get("posted")} for p in ps if p.get("name") or p.get("title")]
            if out:
                return out
        except Exception:
            continue
    return None


def _discover(html, company, domain):
    """Scan one careers page's HTML for ANY known board -> (ats, token, postings), or None."""
    wd = _workday(html)                              # enterprise heavyweight (POST)
    if wd:
        return wd
    for name, rgx, tmpl, norm in _ATS:
        m = re.search(rgx, html, re.I)
        token = next((g for g in (m.groups() if m else ()) if g), None) if m else None
        if token and token.lower() not in ("embed", "www"):
            posts = _try_board(tmpl, token, norm)
            if posts:
                return name, token, posts
    ef = _eightfold(html, domain)
    if ef:
        return "eightfold", domain, ef
    return None


def jobs_search(company: str, domain: str, render: bool = True) -> dict:
    """Company + domain -> its public job postings, from whichever ATS it uses (discovered from
    the careers page, incl. jobs./careers. subdomains), Eightfold, or its own schema.org
    JobPosting markup. If the careers page is JS-rendered and static discovery finds nothing,
    falls back to pith's browser tier (render=True). Raw postings; interpretation is the
    caller's. Honest note when no keyless board is found."""
    slug = domain.split(".")[0]
    # prioritized candidate careers URLs — fetched CONCURRENTLY, scanned in this order so the
    # common case (domain/careers) returns fast without waiting on the long tail of subdomains.
    candidates = [f"https://{domain}/careers", f"https://{domain}/jobs", f"https://www.{domain}/careers",
                  f"https://jobs.{domain}", f"https://careers.{domain}", f"https://{domain}/company/careers",
                  f"https://jobs.{domain}/careers", f"https://careers.{domain}/jobs"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        htmls = list(pool.map(lambda u: (u, _safe_get(u)), candidates))
    for url, html in htmls:                          # priority order = candidate order
        if not html:
            continue
        hit = _discover(html, company, domain)
        if hit:
            return {"company": company, "domain": domain, "ats": hit[0], "token": hit[1],
                    "count": len(hit[2]), "postings": hit[2]}
    # first-party schema.org JobPosting (reuse the pages we already fetched)
    for url, html in htmls:
        if html and (fp := _jobposting_from(html)):
            return {"company": company, "domain": domain, "ats": "first-party", "count": len(fp), "postings": fp}
    # browser-tier fallback: the board link is often injected by JS (Nvidia/Workday, Netflix)
    if render:
        try:
            from .core import _fetch_js
            html = _fetch_js(f"https://{domain}/careers")
            hit = _discover(html, company, domain)
            if hit:
                return {"company": company, "domain": domain, "ats": hit[0], "token": hit[1],
                        "count": len(hit[2]), "postings": hit[2], "via": "browser"}
        except Exception:
            pass
    # last resort: token == slug on the big boards
    for name, _rgx, tmpl, norm in _ATS[:3]:
        posts = _try_board(tmpl, slug, norm)
        if posts:
            return {"company": company, "domain": domain, "ats": name, "token": slug,
                    "count": len(posts), "postings": posts}
    return {"company": company, "domain": domain, "ats": None, "count": 0, "postings": [],
            "note": "no public ATS board or JobPosting markup found (LinkedIn-only / custom site)"}
