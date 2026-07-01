"""Keyless, deterministic buyer-intent news search — the free drop-in for Tavily/paid news APIs.

Given a company, find recent public news and tag each item with a buyer-intent SIGNAL type
(funding / hiring / leadership / security / product / ai / m&a / expansion). No API key, no
LLM: Google News RSS + Bing News RSS (both public, dated), merged, deduped, recency-filtered.
Every fetch goes through pith's SSRF-guarded, gzip-aware _fetch_static.

    from pith.news import news_search
    for item in news_search("Ramp", qualifier="fintech", window_days=30):
        print(item["date"], item["signal"], item["title"], item["url"], item["source"])

Honest limits (surfaced, not hidden): Google News gives volume + dates but its item links are
redirect tokens, not the real article URL (not keyless-recoverable) — those items are SIGNALS
(title/date/source), not directly extractable. Bing gives real, extractable article URLs but
fewer items. A common-word company name ("Ramp", "Apple") needs a `qualifier` to cut noise.
Sources verified 2026-07 on real companies; DuckDuckGo (rate-limited) and GitHub (low signal)
were tested and dropped.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

# deterministic buyer-intent tagging — first category whose keyword hits the title wins.
_SIGNALS = [
    ("funding",    ("funding", "raises", "raised", "valuation", "series a", "series b", "series c",
                    "series d", "series e", "series f", "investment", "venture", "capital", "ipo")),
    ("leadership", ("ceo", "cto", "ciso", "cfo", "coo", "cmo", "appoints", "names ", "joins as",
                    "steps down", "promotes", "elevates", "hires ", "new chief", "president")),
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

_INTENT_QUERY = ('(funding OR raises OR hiring OR CISO OR breach OR launches OR acquires '
                 'OR expansion OR AI OR CEO OR CTO)')


def _signal(title: str) -> str:
    t = " " + title.lower() + " "
    for name, kws in _SIGNALS:
        if any(k in t for k in kws):
            return name
    return "news"


def _parse_date(s: str):
    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _rss_items(xml_text: str, url_is_source_attr: bool):
    """Parse an RSS feed -> [{title, url, date, source}]. Google & Bing are both RSS 2.0."""
    out = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8", "ignore"))
    except ET.ParseError:
        return out
    for it in root.findall(".//item"):
        title = (it.findtext("title") or "").strip()
        if not title:
            continue
        link = (it.findtext("link") or "").strip()
        date = _parse_date(it.findtext("pubDate") or "")
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        out.append({"title": title, "url": link, "date": date, "source": source})
    return out


def _google(company: str, qualifier: str) -> list:
    from .core import _fetch_static
    q = f'"{company}"' + (f" {qualifier}" if qualifier else "") + " " + _INTENT_QUERY
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en"
    items = _rss_items(_fetch_static(url), False)
    for i in items:
        i["provider"], i["extractable"] = "google", False   # link is a redirect token, not the article
    return items


def _bing(company: str, qualifier: str) -> list:
    from .core import _fetch_static
    q = company + (f" {qualifier}" if qualifier else "")
    url = f"https://www.bing.com/news/search?q={quote_plus(q)}&format=rss"
    items = _rss_items(_fetch_static(url), False)
    for i in items:
        i["provider"], i["extractable"] = "bing", True      # real article URL
    return items


def news_search(company: str, qualifier: str | None = None, window_days: int = 90) -> list[dict]:
    """Company -> recent public news, each tagged with a buyer-intent signal. Keyless,
    deterministic. `qualifier` disambiguates common-word names (e.g. 'fintech' for 'Ramp').
    Merges Google + Bing, dedups by title, keeps items within window_days, newest first."""
    company = (company or "").strip()
    if not company:
        return []
    items = []
    for fetch in (_google, _bing):                          # one dead source can't sink the result
        try:
            items += fetch(company, qualifier or "")
        except Exception:
            continue

    cutoff = datetime.now(timezone.utc).timestamp() - window_days * 86400
    seen, out = set(), []
    # prefer the extractable (Bing) copy of a duplicated story
    for it in sorted(items, key=lambda x: (not x["extractable"],)):
        # dedup on the headline WITHOUT the trailing " - Publisher" suffix (Google appends it,
        # Bing doesn't) so the same story from both providers collapses to one.
        head = re.split(r"\s+[-–|]\s+", it["title"])[0]
        key = re.sub(r"\W+", "", head.lower())[:50]
        if not key or key in seen:
            continue
        if it["date"] and it["date"].timestamp() < cutoff:
            continue
        seen.add(key)
        out.append({"title": it["title"], "url": it["url"],
                    "date": it["date"].date().isoformat() if it["date"] else None,
                    "source": it["source"], "signal": _signal(it["title"]),
                    "provider": it["provider"], "extractable": it["extractable"]})
    out.sort(key=lambda x: x["date"] or "", reverse=True)
    return out
