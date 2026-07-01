"""pith — turn any public URL into clean, LLM-ready markdown. Free, no LLM inside.

A drop-in for the Parallel Extract API: same call shape, same result fields, $0.
    from pith import Extractor
    ex = Extractor()
    out = ex.extract(urls=["https://..."])
    for r in out.results:
        print(r.title, r.publish_date, r.emails, r.socials)
        print(r.markdown)      # clean markdown
"""
from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional

import trafilatura

from .extract import enrich as _enrich

log = logging.getLogger("pith")  # silent unless the CLI --verbose installs a handler


def _ms(t0: float) -> float:
    return round((perf_counter() - t0) * 1000, 1)


@dataclass
class Result:
    url: str
    title: Optional[str] = None
    publish_date: Optional[str] = None
    markdown: str = ""                                 # clean extracted markdown of the page
    # deterministic structured data, auto-extracted from the page (no LLM) — the developer
    # gets these for free on every result:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    socials: list[str] = field(default_factory=list)   # linkedin/x/github/... profile URLs
    addresses: list[str] = field(default_factory=list)  # business street addresses (schema.org)
    structured: list[dict] = field(default_factory=list)  # schema.org Person/Organization entities
    meta: dict = field(default_factory=dict)           # OpenGraph + author/date
    facts: list = field(default_factory=list)          # evidence model: Fact(value, sources[url+method], corroboration)


@dataclass
class ExtractResult:
    results: list[Result] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


# --- fetching ---

import os as _os
import socket as _socket
from ipaddress import ip_address as _ip

# pith fetches user-supplied URLs and is now served as an HTTP API — so by default we refuse
# non-web schemes (no file:// local-file read, no gopher/ftp/data) and refuse hosts that
# resolve to private/loopback/link-local/reserved IPs (no SSRF into internal services or
# cloud metadata at 169.254.169.254). Set PITH_ALLOW_LOCAL=1 to opt out for trusted local use.
_ALLOW_LOCAL = _os.environ.get("PITH_ALLOW_LOCAL") == "1"
_FETCH_TIMEOUT = int(_os.environ.get("PITH_FETCH_TIMEOUT", "12"))


class UnsafeURL(ValueError):
    """A URL was rejected before fetch: bad scheme, or resolves to a private/internal host."""


def _guard_url(url: str) -> str:
    if _ALLOW_LOCAL:
        return url
    parts = urllib.parse.urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme not allowed: {parts.scheme or '(none)'} — only http/https")
    host = parts.hostname
    if not host:
        raise UnsafeURL("no host in URL")
    try:                                         # every resolved address must be public
        infos = _socket.getaddrinfo(host, None)
    except Exception as e:
        raise UnsafeURL(f"host does not resolve: {host}") from e
    for info in infos:
        ip = _ip(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise UnsafeURL(f"host resolves to a non-public address ({ip}): {host}")
    return url


# short download timeout so one slow/hostile host can't pin a worker for 30s (trafilatura's default)
_TRAF_CFG = None
def _traf_config():
    global _TRAF_CFG
    if _TRAF_CFG is None:
        from trafilatura.settings import use_config
        c = use_config()
        c.set("DEFAULT", "DOWNLOAD_TIMEOUT", str(_FETCH_TIMEOUT))
        _TRAF_CFG = c
    return _TRAF_CFG


def _fetch_static(url: str) -> str:
    """Fast path: no browser. Works for the ~90% of pages that aren't JS-rendered."""
    _guard_url(url)
    html = trafilatura.fetch_url(url, config=_traf_config())
    if not html:  # trafilatura declined (rare) -> plain urllib
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pith"})
        html = urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT).read().decode("utf-8", "ignore")
    return html


def _fetch_impersonate(url: str) -> str:
    """Middle tier: fetch with a real browser's TLS/JA3 fingerprint via curl_cffi.
    Beats plain-HTTP 403/401s on sites that fingerprint the TLS handshake but still
    serve real HTML (WSJ, some news/B2B) — at ~250ms vs the 5-8s stealth browser.
    Does NOT beat JS-only shells (Reddit/LinkedIn need the browser). Optional dep."""
    try:
        from curl_cffi import requests as creq
    except ImportError as e:
        raise RuntimeError("impersonation tier needs: pip install 'pith[js]'") from e
    _guard_url(url)
    r = creq.get(url, impersonate="chrome", timeout=_FETCH_TIMEOUT)
    r.raise_for_status()
    return r.text


# Non-HTML documents: route through MarkItDown (PDF/Office/epub -> markdown) instead of
# trafilatura, which only understands HTML. Extension-based; covers the common case.
_DOC_EXTS = (".pdf", ".docx", ".pptx", ".xlsx", ".doc", ".ppt", ".xls", ".epub")


def _is_document(url: str) -> bool:
    # ponytail: extension match handles the 90% case; sniff Content-Type if a real
    # doc URL without an extension shows up.
    path = urllib.parse.urlsplit(url).path.lower()
    return path.endswith(_DOC_EXTS)


def _fetch_document(url: str) -> tuple[Optional[str], str]:
    """PDF/Office/epub URL -> (title, markdown) via MarkItDown. Optional [docs] extra."""
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise RuntimeError("document extraction needs: pip install 'pith[docs]'") from e
    _guard_url(url)
    res = MarkItDown().convert(url)
    return getattr(res, "title", None), res.text_content or ""


def _fetch_js(url: str) -> str:
    """JS path: a real stealth browser renders the page, then we read the DOM.

    Settings tuned to clear "network security" walls (Reddit, etc.):
    solve_cloudflare handles Turnstile/interstitial challenges, google_search sets a
    Google referer, and network_idle is off (infinite-scroll feeds never go idle).

    Requires the optional browser extra:  pip install 'pith[js]' && scrapling install
    """
    try:
        from scrapling.fetchers import StealthyFetcher
    except ImportError as e:
        raise RuntimeError(
            "JS rendering needs the browser extra: pip install 'pith[js]' && scrapling install"
        ) from e
    _guard_url(url)
    page = StealthyFetcher.fetch(
        url, headless=True, network_idle=False, timeout=60000,
        solve_cloudflare=True, google_search=True,
    )
    # scrapling returns the rendered HTML; field name has shifted across versions, so be tolerant
    return getattr(page, "html_content", None) or getattr(page, "body", None) or str(page)


# Sites that hard-block plain HTTP at the edge (TLS-fingerprint / "network security" walls)
# and only yield to a real stealth browser loading the human HTML page:
# Walled-garden / bot-protected sites: plain HTTP gets TLS-fingerprint / "network security"
# blocked (403) or served a login wall; only a real stealth browser loading the human HTML
# page yields the public content. (Verified 2026-06.) Matched by registrable domain so
# subdomains count (old.reddit.com, m.facebook.com, etc.).
_BROWSER_ONLY = (
    # social / content (verified yielding public content 2026-06)
    "reddit.com",
    "linkedin.com",
    "instagram.com",
    "facebook.com",
    "threads.net",
    "threads.com",
    "x.com",
    "twitter.com",
    "medium.com",
    # B2B sales-intel sources (live public signals: hiring, funding, reviews, launches)
    "crunchbase.com",   # funding / firmographics
    "indeed.com",       # open roles = hiring intent
    "producthunt.com",  # launches
    "trustpilot.com",   # reviews = competitor displacement
    "glassdoor.com",    # company overview (reviews partially walled)
)


def _needs_browser(url: str) -> bool:
    host = urllib.parse.urlsplit(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in _BROWSER_ONLY)


def _looks_thin(markdown: Optional[str]) -> bool:
    """A near-empty static extract usually means the content is rendered by JS."""
    return not markdown or len(markdown.strip()) < 200


# A browser result this small is usually a transient anti-bot wall (CAPTCHA / rate limit),
# not the real page — worth one more attempt. Genuinely small pages just stay small.
_WALL_RETRY_THRESHOLD = 1000

# Thin extraction escalates to the browser only if the raw HTML was at least this big — big
# HTML + thin markdown = JS shell (fetch it in a browser); small HTML + thin = a real tiny
# page (don't waste ~3s). example.com is 559B raw; SPA shells ship several KB.
_JS_SHELL_MIN_HTML = 3000

# Each stealth-browser fetch spins up a patchright/Chromium instance (hundreds of MB). The cheap
# tiers (HTTP/impersonation) are light and scale wide, but browser fetches must stay
# bounded or a big list OOMs the box. ponytail: 3 is safe on 16GB; bump if you have RAM.
_BROWSER_MAX_CONCURRENCY = 3


def _extract_md(html: str) -> str:
    """HTML -> markdown (links + metadata kept). Empty string if nothing extractable."""
    return trafilatura.extract(
        html, output_format="markdown", include_links=True, with_metadata=True
    ) or ""


def _split_frontmatter(md: str) -> tuple[dict, str]:
    """trafilatura prepends a `--- key: val ---` block when with_metadata=True. Pull it off."""
    meta: dict = {}
    if md.startswith("---"):
        end = md.find("---", 3)
        if end != -1:
            for line in md[3:end].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            md = md[end + 3:].lstrip("\n")
    return meta, md


# --- the client ---

class Extractor:
    """Free Extract client. No API key, no LLM — clean markdown + deterministic structured
    data (emails/socials/schema.org) out. The stealth browser and tier logic are hidden."""

    async def aextract(self, urls, **kw) -> "ExtractResult":
        """Async-friendly extract for callers with a running event loop (FastAPI, async apps).

        pith's fetch stack is threaded, and the browser tier drives Playwright with its own
        loop — calling it directly from a coroutine blocks the caller's loop and can raise
        'event loop already running'. Offloading the whole sync call to a worker thread keeps
        YOUR loop free AND gives the browser its own clean loop in that thread. Await it, or
        asyncio.gather() many — they run concurrently without blocking.

            out = await Extractor().aextract(urls, concurrency=8)
        """
        import asyncio
        return await asyncio.to_thread(self.extract, urls, **kw)

    def extract(
        self,
        urls: list[str],
        render_js: object = "auto",  # "auto" | True | False
        concurrency: int = 1,       # >1 enables tier-aware parallel fetching
    ) -> ExtractResult:
        """Extract clean markdown for each URL. Results preserve input order; a single
        failed URL lands in `.errors`, never sinks the batch.

        concurrency > 1 fetches in parallel — the list-enrichment fast path. Cheap-tier
        URLs (normal sites: HTTP/impersonation) run at full `concurrency`; browser-tier
        URLs (walled gardens) are capped at _BROWSER_MAX_CONCURRENCY since each spins up a
        RAM-heavy stealth browser. Most enrichment lists are company websites = cheap tier,
        so the speedup is large in practice."""
        if concurrency <= 1:
            return self._reassemble(urls, {u: self._extract_one(u, render_js) for u in urls})

        from concurrent.futures import ThreadPoolExecutor
        forces_browser = render_js is True
        browser = [u for u in urls if forces_browser or _needs_browser(u)]
        cheap = [u for u in urls if not (forces_browser or _needs_browser(u))]
        done: dict = {}

        def work(url):
            return url, self._extract_one(url, render_js)

        for group, workers in ((cheap, concurrency),
                               (browser, min(concurrency, _BROWSER_MAX_CONCURRENCY))):
            if not group:
                continue
            with ThreadPoolExecutor(max_workers=workers) as pool:
                done.update(dict(pool.map(work, group)))
        return self._reassemble(urls, done)

    def _extract_one(self, url, render_js):
        """One URL -> Result, or an error dict. The unit of work for the batch loop."""
        t = perf_counter()
        try:
            meta, body, html = self._to_markdown(url, render_js)
            r = Result(url=url, title=meta.get("title"), publish_date=meta.get("date"))
            r.markdown = body
            det = _enrich(body, html, source_url=url)  # deterministic structured data — no LLM
            r.emails, r.phones, r.socials = det["emails"], det["phones"], det["socials"]
            r.addresses = det.get("addresses", [])
            r.structured, r.meta = det["structured"], det["meta"]
            r.facts = det.get("facts", [])   # evidence model: each datum with its source URL + method
            log.info("url_done", extra={"url": url, "ms": _ms(t), "bytes": len(body),
                                        "emails": len(r.emails), "socials": len(r.socials), "ok": True})
            return r
        except Exception as e:  # one bad URL shouldn't sink the batch
            log.info("url_done", extra={"url": url, "ms": _ms(t), "ok": False, "err": str(e)[:120]})
            return {"url": url, "error": str(e)}

    @staticmethod
    def _reassemble(urls, done: dict) -> ExtractResult:
        out = ExtractResult()
        for url in urls:
            r = done[url]
            (out.results if isinstance(r, Result) else out.errors).append(r)
        return out

    def _to_markdown(self, url: str, render_js: object) -> tuple[dict, str, str]:
        """Returns (metadata, markdown body, raw HTML). Raw HTML is '' for documents; it
        feeds deterministic structured extraction (schema.org, contacts)."""
        if _is_document(url):  # PDF/Office/epub -> MarkItDown, not trafilatura
            t = perf_counter()
            title, body = _fetch_document(url)
            log.debug("tier", extra={"url": url, "tier": "document", "ms": _ms(t), "bytes": len(body)})
            if not body:
                raise RuntimeError("no extractable content")
            return ({"title": title} if title else {}), body, ""
        use_browser = render_js is True or _needs_browser(url)  # reddit/linkedin force the browser
        if use_browser:
            md, raw = self._browser_markdown(url)
        else:
            md, raw = self._cheap_markdown(url)  # plain HTTP, then TLS-impersonation if that 403s/thins
            # Escalate to the browser only when extraction was thin BUT the raw HTML was
            # substantial — the JS-shell signature. A genuinely tiny page (small raw HTML)
            # is just small; the browser can't add what isn't there, so skip the ~3s.
            # ponytail: raw-size proxy; a rare <3KB shell won't escalate. Upgrade = sniff for
            # a script-heavy near-empty body.
            if render_js == "auto" and _looks_thin(md) and len(raw) >= _JS_SHELL_MIN_HTML:
                md, raw = self._browser_markdown(url)
        if not md:
            raise RuntimeError("no extractable content")
        meta, body = _split_frontmatter(md)
        return meta, body, raw

    def _cheap_markdown(self, url: str) -> tuple[str, str]:
        """No-browser tiers: plain HTTP, then browser-TLS impersonation if that fails or
        comes up thin. Both are fast (~hundreds of ms). Returns (best markdown, its raw HTML)
        — the raw HTML feeds structured extraction, and its size tells a JS shell (big HTML,
        thin extract) from a genuinely tiny page. Impersonation rescues 403s (WSJ et al.)."""
        md, raw = "", ""
        t = perf_counter()
        try:
            html = _fetch_static(url)
            md, raw = _extract_md(html), html
        except Exception as e:
            log.debug("tier_fail", extra={"url": url, "tier": "static", "err": str(e)[:80]})
        if not _looks_thin(md):
            log.debug("tier", extra={"url": url, "tier": "static", "ms": _ms(t), "bytes": len(md)})
            return md, raw
        t = perf_counter()
        try:
            html = _fetch_impersonate(url)
            imp = _extract_md(html)
            if len(imp) > len(md):
                md, raw = imp, html
            elif not raw:
                raw = html
            log.debug("tier", extra={"url": url, "tier": "impersonate", "ms": _ms(t), "bytes": len(md)})
        except Exception as e:
            log.debug("tier_fail", extra={"url": url, "tier": "impersonate", "err": str(e)[:80]})
        return md, raw

    def _browser_markdown(self, url: str, attempts: int = 2) -> str:
        """Render in the stealth browser, retrying when the result looks like a transient
        wall. Returns the best (largest) markdown seen; '' if every attempt was empty."""
        best, best_html = "", ""
        for i in range(attempts):
            t = perf_counter()
            html = _fetch_js(url)
            md = _extract_md(html)
            log.debug("tier", extra={"url": url, "tier": "browser", "attempt": i + 1,
                                     "ms": _ms(t), "bytes": len(md)})
            if len(md.strip()) >= _WALL_RETRY_THRESHOLD:
                return md, html  # real content — done
            if len(md) > len(best):
                best, best_html = md, html
        return best, best_html
