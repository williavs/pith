"""freextract examples — mirrors the Parallel Extract API call shape."""
from pith import Extractor

ex = Extractor()  # no API key needed for markdown

# 1) clean markdown from a normal page
out = ex.extract(urls=["https://www.un.org/en/about-us/history-of-the-un"])
for r in out.results:
    print(r.title, "·", r.publish_date)
    print(r.excerpts[0][:300], "…\n")

# 2) objective-focused excerpts (needs a free GROQ_API_KEY)
out = ex.extract(
    urls=["https://www.un.org/en/about-us/history-of-the-un"],
    objective="When was the United Nations established?",
)
for r in out.results:
    for e in r.excerpts:
        print(e)

# 3) a JS-rendered / bot-protected page (Reddit, LinkedIn, …) — needs: pip install 'freextract[js]' && scrapling install
out = ex.extract(urls=["https://www.reddit.com/r/python/"], render_js=True)
for r in out.results:
    print(r.title)
    print(r.excerpts[0][:300])
for err in out.errors:
    print("error:", err)
