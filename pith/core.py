"""pith — turn any public URL into clean, LLM-ready markdown. Free.

A drop-in for the Parallel Extract API: same call shape, same result fields, $0.
    from pith import Extractor
    ex = Extractor()
    out = ex.extract(urls=["https://..."], objective="when was it founded?")
    for r in out.results:
        print(r.title, r.publish_date)
        for e in r.excerpts:
            print(e)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import trafilatura


@dataclass
class Result:
    url: str
    title: Optional[str] = None
    publish_date: Optional[str] = None
    excerpts: list[str] = field(default_factory=list)  # markdown passages (objective-focused, or full content)
    full_content: Optional[str] = None                 # full page markdown, if full_content=True


@dataclass
class ExtractResult:
    results: list[Result] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


# --- fetching ---

def _fetch_static(url: str) -> str:
    """Fast path: no browser. Works for the ~90% of pages that aren't JS-rendered."""
    html = trafilatura.fetch_url(url)
    if not html:  # trafilatura declined (rare) -> plain urllib
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pith"})
        html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")
    return html


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
    """Free Extract client. No API key needed for markdown; an LLM key (Groq, free)
    is only used when you pass an `objective` to get focused excerpts."""

    def __init__(
        self,
        llm_api_key: Optional[str] = None,
        llm_model: str = "llama-3.3-70b-versatile",
        llm_base_url: str = "https://api.groq.com/openai/v1",
    ):
        # any OpenAI-compatible endpoint works; Groq's free tier is the default
        self.llm_api_key = llm_api_key or os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.llm_model = llm_model
        self.llm_base_url = llm_base_url.rstrip("/")

    def extract(
        self,
        urls: list[str],
        objective: Optional[str] = None,
        full_content: bool = False,
        render_js: object = "auto",  # "auto" | True | False
    ) -> ExtractResult:
        out = ExtractResult()
        for url in urls:
            try:
                meta, body = self._to_markdown(url, render_js)
                r = Result(url=url, title=meta.get("title"), publish_date=meta.get("date"))
                if full_content:
                    r.full_content = body
                r.excerpts = self._excerpts(body, objective) if objective else [body]
                out.results.append(r)
            except Exception as e:  # one bad URL shouldn't sink the batch
                out.errors.append({"url": url, "error": str(e)})
        return out

    def _to_markdown(self, url: str, render_js: object) -> tuple[dict, str]:
        use_browser = render_js is True or _needs_browser(url)  # reddit/linkedin force the browser
        if use_browser:
            md = self._browser_markdown(url)
        else:
            md = _extract_md(_fetch_static(url))
            if render_js == "auto" and _looks_thin(md):
                md = self._browser_markdown(url)  # static came up thin → it's JS-rendered
        if not md:
            raise RuntimeError("no extractable content")
        return _split_frontmatter(md)

    def _browser_markdown(self, url: str, attempts: int = 2) -> str:
        """Render in the stealth browser, retrying when the result looks like a transient
        wall. Returns the best (largest) markdown seen; '' if every attempt was empty."""
        best = ""
        for _ in range(attempts):
            md = _extract_md(_fetch_js(url))
            if len(md.strip()) >= _WALL_RETRY_THRESHOLD:
                return md  # real content — done
            if len(md) > len(best):
                best = md
        return best

    def _excerpts(self, markdown: str, objective: str) -> list[str]:
        """One LLM call: return the passages that answer the objective."""
        if not self.llm_api_key:
            # no key — the clean markdown is still the product; hand it back whole
            return [markdown]
        body = json.dumps({
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "Return only the verbatim passages from the document that answer the objective, as a short markdown list. No preamble, no commentary."},
                {"role": "user", "content": f"Objective: {objective}\n\nDocument:\n{markdown[:14000]}"},
            ],
        }).encode()
        req = urllib.request.Request(
            f"{self.llm_base_url}/chat/completions", data=body,
            headers={"Authorization": f"Bearer {self.llm_api_key}", "Content-Type": "application/json"},
        )
        resp = json.load(urllib.request.urlopen(req, timeout=60))
        return [resp["choices"][0]["message"]["content"]]
