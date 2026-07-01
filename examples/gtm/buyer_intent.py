"""pith inside a BUYER-INTENT pipeline — the signal-raccoon integration.

signal-raccoon (Gab's SSPM buyer-intent scorer) runs: firmographics -> summary -> news search
-> *article extraction* -> LLM intent analysis + Python firmographic scoring -> consolidated
0-100 score. pith is the free, deterministic drop-in for the EXTRACTION stage (it's
Parallel-Extract compatible) AND it hands the pipeline free deterministic signals the scorer
can use without an LLM.

Division of labour that fits her architecture ("the LLM finds signals, Python does the math"):
  - pith (deterministic, no LLM, async): extract article text; surface tech stack, leadership
    hires, and a hiring signal — the EVIDENCE.
  - the app's LLM: reads the article text for nuanced intent.
  - the app's Python: scores. Same input -> same score.

Async throughout, because her stack is async (this was the real blocker — pith blocked the
event loop; aextract fixes it). Run:  python examples/gtm/buyer_intent.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith import Extractor
from pith import recipes


async def intent_evidence(company: str, website: str, qualifier: str | None = None) -> dict:
    """The deterministic evidence bundle pith contributes to a buyer-intent score — gathered
    concurrently, never blocking the caller's event loop. pith now owns the news SEARCH too
    (news_search, keyless — replaces Tavily), not just the extraction."""
    from pith.cli import website_intel, contact_evidence
    from pith.news import news_search

    ex = Extractor()
    from pith.cli import _registrable
    dom = _registrable(website)
    # STAGE 3 (news search) + tech + leadership, concurrently
    news, intel, contact = await asyncio.gather(
        asyncio.to_thread(news_search, company, dom, qualifier, 45),  # keyless multi-source news (was Tavily)
        asyncio.to_thread(website_intel, website),                    # tech posture (SSPM-relevant)
        asyncio.to_thread(contact_evidence, website),                 # leadership / new-hire signal
    )
    # STAGE 4: extract the articles pith CAN fetch (the extractable/Bing ones) for the LLM analyzer
    extract_urls = [n["url"] for n in news if n["extractable"] and n["url"]][:8]
    articles = await ex.aextract(extract_urls, concurrency=6) if extract_urls else Extractor().extract([])

    people = recipes.people(contact["facts"])
    careers_signal = any("career" in u.lower() or "/job" in u.lower() for u in contact["coverage"].ok)
    from collections import Counter
    return {
        "company": company,
        "website": website,
        # --- deterministic signals (Python can score these directly, no LLM) ---
        "signals": {
            "tech_grade": intel.get("modernness_grade"),
            "builder": intel.get("builder"),
            "framework": intel.get("framework"),
            "leadership": people,                              # [{name,title,rel,...}] — a new exec = intent
            "hiring": careers_signal,                          # careers page present = growth
            "news_signals": dict(Counter(n["signal"] for n in news)),  # {funding: 19, leadership: 6, ...}
            "recent_news": news[:12],                          # dated, tagged headlines (was Tavily's job)
        },
        # --- extracted article text for the LLM intent analyzer (pith replaces Parallel.ai here) ---
        "articles": [{"url": r.url, "title": r.title, "text": r.markdown[:4000]} for r in articles.results],
        "extraction_errors": [str(e) for e in articles.errors],
    }


async def main():
    company = sys.argv[1] if len(sys.argv) > 1 else "Ramp"
    website = sys.argv[2] if len(sys.argv) > 2 else "https://ramp.com"
    qualifier = sys.argv[3] if len(sys.argv) > 3 else "fintech"   # disambiguate a common-word name
    ev = await intent_evidence(company, website, qualifier)
    s = ev["signals"]
    print(f"BUYER-INTENT EVIDENCE: {ev['company']} ({ev['website']})")
    print(f"  tech:       {s['tech_grade']} · {s['builder']} · {s['framework'] or '-'}")
    print(f"  hiring:     {'careers page found' if s['hiring'] else 'no hiring signal'}")
    print(f"  leadership: {', '.join(f'{p['name']} ({p['title'] or '?'})' for p in s['leadership']) or '(none in structured data)'}")
    print(f"  news:       {s['news_signals']}")
    for n in s["recent_news"][:6]:
        print(f"    [{n['date']}] {n['signal']:10} {n['title'][:60]}")
    print(f"  articles:   {len(ev['articles'])} extracted for the LLM intent analyzer")
    print("\n> pith now owns SEARCH (news_search, keyless) + EXTRACTION + deterministic signals —")
    print("> free, async, no LLM. signal-raccoon's LLM reads the text, its Python scores. No Tavily.")


if __name__ == "__main__":
    asyncio.run(main())
