"""Thorough walled-garden test: one real public URL per site, report what actually comes through."""
import re
import sys
from pith import Extractor

# real, public, stable URLs (profiles/pages that exist without login)
TARGETS = {
    "reddit-sub":    "https://www.reddit.com/r/Python/",
    "reddit-post":   "https://www.reddit.com/r/Python/comments/1txuzkb/",
    "linkedin-co":   "https://www.linkedin.com/company/nasa/",
    "linkedin-person": "https://www.linkedin.com/in/williamhgates/",
    "instagram-prof": "https://www.instagram.com/nasa/",
    "facebook":      "https://www.facebook.com/NASA/",
    "threads":       "https://www.threads.net/@nasa",
    "x":             "https://x.com/NASA",
    "tiktok":        "https://www.tiktok.com/@nasa",
    "quora":         "https://www.quora.com/profile/Bill-Gates-1",
    "medium":        "https://medium.com/@dhh",
    # B2B sales-intel sources — live public signals
    "crunchbase":    "https://www.crunchbase.com/organization/stripe",
    "g2":            "https://www.g2.com/products/slack/reviews",
    "glassdoor":     "https://www.glassdoor.com/Overview/Working-at-Stripe-EI_IE671932.11,17.htm",
    "indeed":        "https://www.indeed.com/cmp/Stripe/jobs",
    "producthunt":   "https://www.producthunt.com/products/notion",
    "wellfound":     "https://wellfound.com/company/stripe",
    "trustpilot":    "https://www.trustpilot.com/review/stripe.com",
    "builtwith":     "https://builtwith.com/stripe.com",
}

WALL_HINTS = ("log in", "sign in", "create account", "isn't available", "page not found",
              "enable javascript", "something went wrong", "join now to see")

ex = Extractor()
only = sys.argv[1:] or list(TARGETS)
for name in only:
    url = TARGETS[name]
    try:
        out = ex.extract(urls=[url])
        if out.errors:
            print(f"✗ {name:18} ERROR: {out.errors[0]['error'][:70]}")
            continue
        r = out.results[0]
        md = r.excerpts[0]
        n = len(md)
        clean = re.sub(r"\s+", " ", md).strip()
        walled = sum(h in clean.lower() for h in WALL_HINTS)
        # a real content page is big and not dominated by wall text
        verdict = "✓ content" if n > 1500 and walled <= 2 else ("~ partial/wall" if n > 400 else "✗ blocked/thin")
        print(f"{verdict:16} {name:18} {n:>6}B  title={str(r.title)[:40]!r}")
        print(f"                   preview: {clean[:130]}")
    except Exception as e:
        print(f"✗ {name:18} EXC: {str(e)[:70]}")
