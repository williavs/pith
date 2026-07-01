"""pith examples — URL -> clean markdown + deterministic structured data. No LLM, no key."""
from pith import Extractor

ex = Extractor()

# 1) clean markdown from a normal page
out = ex.extract(urls=["https://www.un.org/en/about-us/history-of-the-un"])
for r in out.results:
    print(r.title, "·", r.publish_date)
    print(r.excerpts[0][:300], "…\n")

# 2) structured data, auto-extracted (no LLM): emails, socials, schema.org, meta
out = ex.extract(urls=["https://www.anthropic.com/company"])
for r in out.results:
    print("emails:", r.emails)
    print("socials:", r.socials)
    print("structured:", r.structured)

# 3) a batch, concurrent — the list-enrichment fast path (needs pip install 'pith[js]')
out = ex.extract(urls=["https://stripe.com", "https://linear.app"], concurrency=8)
for r in out.results:
    print(r.url, "→", r.socials)
for err in out.errors:
    print("error:", err)
