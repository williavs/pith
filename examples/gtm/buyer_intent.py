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


async def intent_evidence(company: str, website: str, news_urls: list[str]) -> dict:
    """The deterministic evidence bundle pith contributes to a buyer-intent score — gathered
    concurrently, never blocking the caller's event loop."""
    from pith.cli import website_intel, contact_evidence

    ex = Extractor()
    # all four pith calls run concurrently; the sync ones are offloaded to threads
    articles, intel, contact = await asyncio.gather(
        ex.aextract(news_urls, concurrency=6),                 # STAGE 4: article extraction (was Parallel.ai)
        asyncio.to_thread(website_intel, website),             # tech posture (SSPM-relevant)
        asyncio.to_thread(contact_evidence, website),          # leadership / new-hire signal
    )

    people = recipes.people(contact["facts"])
    careers_signal = any("career" in u.lower() or "/job" in u.lower() for u in contact["coverage"].ok)
    return {
        "company": company,
        "website": website,
        # --- deterministic signals (Python can score these directly, no LLM) ---
        "signals": {
            "tech_grade": intel.get("modernness_grade"),
            "builder": intel.get("builder"),
            "framework": intel.get("framework"),
            "https": intel.get("https"),
            "leadership": people,                              # [{name,title,rel,...}] — a new exec = intent
            "hiring": careers_signal,                          # careers page present = growth
        },
        # --- extracted article text for the LLM intent analyzer (pith replaces Parallel.ai here) ---
        "articles": [{"url": r.url, "title": r.title, "text": r.markdown[:4000]} for r in articles.results],
        "extraction_errors": [str(e) for e in articles.errors],
    }


async def main():
    # a real, public example: a company + a couple of public news/blog URLs about it
    ev = await intent_evidence(
        "GitLab", "https://about.gitlab.com",
        ["https://about.gitlab.com/blog/", "https://en.wikipedia.org/wiki/GitLab"],
    )
    s = ev["signals"]
    print(f"BUYER-INTENT EVIDENCE: {ev['company']} ({ev['website']})")
    print(f"  tech:       {s['tech_grade']} · {s['builder']} · {s['framework'] or '-'}")
    print(f"  hiring:     {'careers page found' if s['hiring'] else 'no hiring signal'}")
    print(f"  leadership: {', '.join(f'{p['name']} ({p['title'] or '?'})' for p in s['leadership']) or '(none in structured data)'}")
    print(f"  articles:   {len(ev['articles'])} extracted for the LLM intent analyzer"
          f"{', ' + str(len(ev['extraction_errors'])) + ' failed' if ev['extraction_errors'] else ''}")
    for a in ev["articles"]:
        print(f"    - {(a['title'] or a['url'])[:70]}  ({len(a['text'])} chars)")
    print("\n> pith supplies the extraction + deterministic signals (free, async, no LLM);")
    print("> signal-raccoon's LLM reads the article text and its Python does the scoring.")


if __name__ == "__main__":
    asyncio.run(main())
