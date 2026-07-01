"""Keyless, deterministic buyer-intent news search — the free drop-in for Tavily/paid news APIs.

Given a company, find recent public news and tag each item with a buyer-intent SIGNAL
(funding / leadership / security / m&a / hiring / product / ai / expansion). No API key, no
LLM. Sources were verified live on real companies (2026-07); the ones that hand back REAL,
EXTRACTABLE article URLs win — so pith can then fetch + extract the article, not just show a
headline:

  - Hacker News (Algolia API)   keyless JSON, real URLs, dated, points — strong B2B/tech intent
  - Bing News RSS               keyless, real URLs, dated, broad coverage
  - company blog/newsroom RSS   first-party, real URLs, dated — decisive launch/funding signal
  - Google News RSS             high VOLUME + dates, but its links are redirect tokens (NOT the
                                real URL) — kept as signal-only, clearly flagged extractable=False

Dropped (verified, with reasons): DuckDuckGo (rate-limited, no native dates), Reddit JSON
(403s datacenter IPs), GDELT (429/non-JSON without heavy backoff), GitHub (low buyer-intent
signal). Every fetch is SSRF-guarded. A common-word name ("Ramp", "Apple") needs a `qualifier`.
"""
from __future__ import annotations

import gzip
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

_SIGNALS = [
    ("funding",    ("funding", "raises", "raised", "valuation", "series a", "series b", "series c",
                    "series d", "series e", "series f", "investment", "venture", "capital", "ipo")),
    ("leadership", ("ceo", "cto", "ciso", "cfo", "coo", "cmo", "appoints", "names ", "joins as",
                    "steps down", "promotes", "elevates", "new chief", "president", "chair")),
    ("security",   ("breach", "hack", "vulnerability", "ransomware", "exposed", "leak", "cve-",
                    "data leak", "attack", "compromised", "exploit")),
    ("m&a",        ("acquires", "acquisition", "acquired", "merger", "merges", "buys ", "to buy")),
    ("hiring",     ("hiring", "headcount", "expands team", "layoff", "layoffs", "cuts jobs", "workforce")),
    ("product",    ("launches", "launch", "unveils", "releases", "introducing", "introduces",
                    "announces", "ships", "now available", "general availability", "version")),
    ("ai",         ("ai ", "a.i.", "artificial intelligence", "machine learning", "llm", "genai",
                    "gpt", "copilot", "agentic")),
    ("expansion",  ("expansion", "expands", "opens office", "new office", "enters", "global")),
]


def _signal(title: str) -> str:
    t = " " + title.lower() + " "
    for name, kws in _SIGNALS:
        if any(k in t for k in kws):
            return name
    return "news"


def _get(url: str, timeout: int = 15) -> str:
    """SSRF-guarded keyless fetch (RSS or JSON), gzip-aware."""
    from .core import _guard_url
    _guard_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pith", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return data.decode("utf-8", "ignore")


def _date(dt):
    return dt.date().isoformat() if dt else None


def _parse_rfc822(s):
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ---- sources (each best-effort; one dead source never sinks the result) ----

def _hn(company, qualifier):
    """Hacker News via the keyless Algolia API — real URLs, dated, points-ranked."""
    q = urllib.parse.quote(company + (f" {qualifier}" if qualifier else ""))
    d = json.loads(_get(f"https://hn.algolia.com/api/v1/search_by_date?query={q}&tags=story&hitsPerPage=30"))
    out = []
    for h in d.get("hits", []):
        title, url = h.get("title") or h.get("story_title"), h.get("url")
        if not title:
            continue
        ts = h.get("created_at_i")
        dt = datetime.fromtimestamp(ts, timezone.utc) if ts else None
        ext = bool(url)
        out.append({"title": title, "url": url or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                    "date": dt, "source": "Hacker News", "provider": "hn", "extractable": ext})
    return out


def _bing(company, qualifier):
    """Bing News RSS — keyless, real article URLs, dated, broad."""
    q = urllib.parse.quote(company + (f" {qualifier}" if qualifier else ""))
    return _rss(_get(f"https://www.bing.com/news/search?q={q}&format=rss"), "bing", True)


def _google(company, qualifier):
    """Google News RSS — high volume + dates, but links are redirect tokens (signal-only)."""
    q = urllib.parse.quote(f'"{company}"' + (f" {qualifier}" if qualifier else "") +
                           " (funding OR raises OR hiring OR CISO OR breach OR launches OR acquires OR AI OR CEO)")
    return _rss(_get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"), "google", False)


def _blog(domain):
    """First-party blog/newsroom RSS — real URLs, dated, decisive launch/funding signal. Probes
    the common feed paths, then falls back to the <link rel=alternate rss> on the blog page."""
    bases = [f"https://{domain}", f"https://www.{domain}"]
    paths = ["/blog/feed.rss", "/blog/feed", "/blog/rss", "/blog/feed.xml", "/blog/atom",
             "/feed", "/rss", "/atom", "/feed.xml", "/news/feed", "/newsroom/feed", "/blog/rss.xml"]
    for base in bases:
        for p in paths:
            try:
                items = _rss(_get(base + p), "blog", True)
                if items:
                    return items
            except Exception:
                continue
        try:                                       # discover from the blog page's <link rel=alternate>
            html = _get(base + "/blog")
            m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]+href=["\']([^"\']+)', html, re.I) \
                or re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+type=["\']application/(?:rss|atom)\+xml', html, re.I)
            if m:
                return _rss(_get(urllib.parse.urljoin(base + "/blog", m.group(1))), "blog", True)
        except Exception:
            continue
    return []


def _rss(xml_text, provider, extractable):
    """Parse RSS 2.0 OR Atom -> normalized items."""
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8", "ignore"))
    except ET.ParseError:
        return out
    ns = {"a": "http://www.w3.org/2005/Atom"}
    nodes = root.findall(".//item") or root.findall(".//a:entry", ns)
    for it in nodes:
        title = (it.findtext("title") or it.findtext("a:title", "", ns) or "").strip()
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        if not link:                               # atom: <link href=...> (empty Element is falsy — use is None)
            le = it.find("a:link", ns)
            if le is None:
                le = it.find("link")
            link = (le.get("href") if le is not None else "") or ""
        raw = it.findtext("pubDate") or it.findtext("a:updated", "", ns) or it.findtext("a:published", "", ns) or ""
        dt = _parse_rfc822(raw)
        if dt is None and raw:                     # atom ISO date
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                dt = None
        src_el = it.find("source")
        source = (src_el.text or "").strip() if (src_el is not None and src_el.text) else provider.title()
        out.append({"title": title, "url": link, "date": dt, "source": source,
                    "provider": provider, "extractable": extractable})
    return out


def news_search(company: str, domain: str | None = None, qualifier: str | None = None,
                window_days: int = 90) -> list[dict]:
    """Company -> recent public news, each tagged with a buyer-intent signal. Keyless,
    deterministic, real URLs where possible. `domain` adds the company's first-party blog feed;
    `qualifier` disambiguates common-word names (e.g. 'fintech' for 'Ramp'). Merges HN + Bing +
    Google (+ blog), dedups by headline, keeps items within window_days, newest first."""
    company = (company or "").strip()
    if not company:
        return []
    items = []
    for src in (lambda: _hn(company, qualifier or ""),
                lambda: _bing(company, qualifier or ""),
                lambda: _google(company, qualifier or ""),
                (lambda: _blog(domain)) if domain else (lambda: [])):
        try:
            items += src()
        except Exception:
            continue

    cutoff = datetime.now(timezone.utc).timestamp() - window_days * 86400
    seen, out = set(), []
    # prefer the extractable copy of a duplicated story (HN/Bing/blog over Google's redirect)
    for it in sorted(items, key=lambda x: (not x["extractable"],)):
        head = re.split(r"\s+[-–|]\s+", it["title"])[0]
        key = re.sub(r"\W+", "", head.lower())[:50]
        if not key or key in seen:
            continue
        if it["date"] and it["date"].timestamp() < cutoff:
            continue
        seen.add(key)
        out.append({"title": it["title"], "url": it["url"], "date": _date(it["date"]),
                    "source": it["source"], "signal": _signal(it["title"]),
                    "provider": it["provider"], "extractable": it["extractable"]})
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out
