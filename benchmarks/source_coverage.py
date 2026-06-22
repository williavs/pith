"""Honest source-coverage runner. Hits every candidate source with a real public URL,
runs the full pith pipeline, and classifies what actually comes through. No fabrication —
the README source table is built from THIS output. Run: python benchmarks/source_coverage.py
"""
import re
import sys
import time

from pith import Extractor

# (id, category, url) — real, public URLs
TARGETS = [
    # --- walled social/content (in _BROWSER_ONLY: forced through stealth browser) ---
    ("reddit",        "social",  "https://www.reddit.com/r/Python/"),
    ("linkedin_co",   "social",  "https://www.linkedin.com/company/nasa/"),
    ("linkedin_pers", "social",  "https://www.linkedin.com/in/williamhgates/"),
    ("instagram",     "social",  "https://www.instagram.com/nasa/"),
    ("x",             "social",  "https://x.com/NASA"),
    ("facebook",      "social",  "https://www.facebook.com/NASA/"),
    ("threads",       "social",  "https://www.threads.net/@nasa"),
    ("medium",        "social",  "https://medium.com/@dhh"),
    # --- B2B sales intel (in _BROWSER_ONLY) ---
    ("crunchbase",    "b2b",     "https://www.crunchbase.com/organization/stripe"),
    ("indeed",        "b2b",     "https://www.indeed.com/cmp/Stripe/jobs"),
    ("producthunt",   "b2b",     "https://www.producthunt.com/products/notion"),
    ("trustpilot",    "b2b",     "https://www.trustpilot.com/review/stripe.com"),
    ("glassdoor",     "b2b",     "https://www.glassdoor.com/Overview/Working-at-Stripe-EI_IE671932.11,17.htm"),
    # --- news / paywall (NOT in _BROWSER_ONLY: static path; the 9 from the bogus table) ---
    ("arxiv",         "public",  "https://arxiv.org/abs/1706.03762"),
    ("github",        "public",  "https://github.com/charmbracelet/bubbletea"),
    ("guardian",      "news",    "https://www.theguardian.com/technology"),
    ("bbc",           "news",    "https://www.bbc.com/news/technology"),
    ("substack",      "news",    "https://newsletter.pragmaticengineer.com/archive"),
    ("nytimes",       "paywall", "https://www.nytimes.com/section/technology"),
    ("bloomberg",     "paywall", "https://www.bloomberg.com/technology"),
    ("wsj",           "paywall", "https://www.wsj.com/tech"),
    ("ft",            "paywall", "https://www.ft.com/technology"),
]

WALL = ("you must log in", "sign in to continue", "are you a robot", "verify you are human",
        "subscribe to continue", "subscribe to read", "create a free account",
        "enable javascript", "access denied", "something went wrong. wait a moment")


def classify(md: str) -> str:
    low = re.sub(r"\s+", " ", md).strip().lower()
    n = len(md)
    if n < 250:
        return "blocked"
    if sum(w in low for w in WALL) >= 2 and n < 2000:
        return "wall"
    return "content" if n >= 1500 else "partial"


def main() -> None:
    ex = Extractor()
    ids = sys.argv[1:]
    for tid, cat, url in TARGETS:
        if ids and tid not in ids:
            continue
        t = time.time()
        try:
            out = ex.extract(urls=[url])
            if out.errors:
                verdict, n, note = "error", 0, out.errors[0]["error"][:55]
            else:
                md = out.results[0].excerpts[0]
                n = len(md)
                verdict = classify(md)
                note = re.sub(r"\s+", " ", md).strip()[:60]
        except Exception as e:  # noqa: BLE001
            verdict, n, note = "error", 0, str(e)[:55]
        mark = {"content": "✓", "partial": "~"}.get(verdict, "✗")
        print(f"{mark} {verdict:8} {tid:14} {cat:8} {n:>7}B {time.time()-t:5.1f}s  {note}", flush=True)


if __name__ == "__main__":
    main()
