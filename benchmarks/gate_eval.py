"""Fetch-budget gate eval — does a scorer rank buyer-signal URLs above junk, BEFORE fetching?

The gate's job: given ~40 candidate URLs for a target, spend the expensive ~4-5s walled
fetches only on the ones carrying signal. This measures any scorer `score(query, url) -> float`
against a labeled set: the 12 real dossier sources (signal) + plausible-but-irrelevant junk.

Metrics (the honest numbers):
  - precision@12         : of the top-12 ranked, how many are real signal
  - wasted-fetch cut     : fetches saved to reach 90% of signal vs fetch-everything-in-order
Swap in the real embedder scorer when the research pick lands; a keyword baseline runs now
so the harness is proven end-to-end.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TARGET = {"name": "Matt MacInnis", "company": "Rippling"}
QUERY = "buyer intent signals about Matt MacInnis, Chief Product Officer at Rippling"

# label = True if the URL carries real signal about THIS target (from the dossier run)
SIGNAL = [
    "https://www.linkedin.com/posts/roshan-oommen-6a87131a3_ai-futureofwork-hrtech-activity-7460001797101842433-k0e-",
    "https://www.instagram.com/reel/DW4jJasiOwH",
    "https://www.reddit.com/r/rippling/comments/1sll2br/im_matt_macinnis_chief_product_officer_at",
    "https://x.com/Rippling",
    "https://www.crunchbase.com/organization/rippling",
    "https://www.indeed.com/cmp/Rippling/jobs",
    "https://www.glassdoor.com/Overview/Working-at-Rippling-EI_IE2452185.11,19.htm",
    "https://www.trustpilot.com/review/rippling.com",
    "https://www.rippling.com/",
    "https://www.rippling.com/blog",
    "https://www.linkedin.com/in/mattmacinnis",
    "https://www.rippling.com/about",
]
# plausible candidates a crawler/search would surface, but NOT signal for this target
JUNK = [
    "https://www.linkedin.com/in/some-other-person-2847",      # wrong person
    "https://www.crunchbase.com/organization/deel",            # competitor
    "https://www.crunchbase.com/organization/gusto",           # competitor
    "https://www.reddit.com/r/personalfinance/comments/abc",   # unrelated subreddit
    "https://www.indeed.com/cmp/Workday/jobs",                 # different company
    "https://www.glassdoor.com/Overview/Working-at-Deel.htm",  # competitor
    "https://www.rippling.com/privacy",                        # boilerplate page
    "https://www.rippling.com/terms",                          # boilerplate
    "https://www.rippling.com/cookie-policy",                  # boilerplate
    "https://www.instagram.com/explore/tags/payroll",          # generic tag
    "https://x.com/elonmusk",                                  # unrelated celebrity
    "https://www.trustpilot.com/review/adp.com",              # competitor reviews
    "https://www.reddit.com/r/aww",                            # noise
    "https://www.linkedin.com/company/microsoft",              # unrelated big co
    "https://medium.com/@random/how-i-cook-pasta-12ab",       # off-topic blog
    "https://www.producthunt.com/products/some-random-app",    # unrelated launch
    "https://www.facebook.com/SomeLocalBakery",                # unrelated
    "https://www.indeed.com/cmp/Starbucks/jobs",               # unrelated
    "https://www.crunchbase.com/organization/openai",          # unrelated
    "https://www.glassdoor.com/Overview/Working-at-Amazon.htm",# unrelated
]

CANDIDATES = [(u, True) for u in SIGNAL] + [(u, False) for u in JUNK]

# Realistic search-result snippets (title + blurb) a search/crawl would surface per URL.
# This is the embedder's FAIR condition: static embeddings rank on text, not bare URLs.
SNIPPETS = {
    SIGNAL[0]: "Matt MacInnis on LinkedIn: Rippling AI launch — agentic platform across HR, IT, finance",
    SIGNAL[1]: "Rippling on Instagram: our CPO Matt MacInnis on the AI prototype that hit real data",
    SIGNAL[2]: "I'm Matt MacInnis, Chief Product Officer at Rippling. AMA — r/rippling",
    SIGNAL[3]: "Rippling (@Rippling) on X — HR, IT and finance in one platform",
    SIGNAL[4]: "Rippling - Crunchbase Company Profile: funding rounds, investors, revenue",
    SIGNAL[5]: "Rippling Careers and Jobs | Indeed.com — open roles, hiring",
    SIGNAL[6]: "Working at Rippling | Glassdoor — company overview and reviews",
    SIGNAL[7]: "Rippling Reviews | Read Customer Service Reviews of rippling.com — Trustpilot",
    SIGNAL[8]: "Rippling: HR, IT, and Finance on one platform",
    SIGNAL[9]: "Rippling Blog — product updates, AI, workforce management",
    SIGNAL[10]: "Matt MacInnis - Chief Product Officer at Rippling | LinkedIn profile",
    SIGNAL[11]: "About Rippling — our mission, leadership, and team",
    JUNK[0]: "John Doe - Sales Manager at Acme | LinkedIn",
    JUNK[1]: "Deel - Crunchbase Company Profile: global payroll and compliance",
    JUNK[2]: "Gusto - Crunchbase Company Profile: small-business payroll",
    JUNK[3]: "How do I budget my first paycheck? : r/personalfinance",
    JUNK[4]: "Workday Careers and Jobs | Indeed.com",
    JUNK[5]: "Working at Deel | Glassdoor reviews",
    JUNK[6]: "Privacy Policy | Rippling",
    JUNK[7]: "Terms of Service | Rippling",
    JUNK[8]: "Cookie Policy | Rippling",
    JUNK[9]: "#payroll hashtag photos and videos • Instagram",
    JUNK[10]: "Elon Musk (@elonmusk) on X",
    JUNK[11]: "ADP Reviews | Trustpilot",
    JUNK[12]: "r/aww — cute animals",
    JUNK[13]: "Microsoft | LinkedIn company page",
    JUNK[14]: "How I cook the perfect pasta — a Medium story",
    JUNK[15]: "Some Random App - Product Hunt launch",
    JUNK[16]: "Some Local Bakery | Facebook",
    JUNK[17]: "Starbucks Careers and Jobs | Indeed.com",
    JUNK[18]: "OpenAI - Crunchbase Company Profile",
    JUNK[19]: "Working at Amazon | Glassdoor",
}


def evaluate(scorer, name: str):
    """scorer: (query, url) -> float. Prints precision@K + wasted-fetch cut."""
    ranked = sorted(CANDIDATES, key=lambda c: scorer(QUERY, c[0]), reverse=True)
    k = len(SIGNAL)
    p_at_k = sum(1 for u, lab in ranked[:k] if lab) / k

    # wasted-fetch cut: how many fetches to reach 90% of signal, gated vs fetch-all-in-order
    need = int(0.9 * len(SIGNAL) + 0.999)
    def fetches_to_target(order):
        got = 0
        for i, (u, lab) in enumerate(order, 1):
            if lab:
                got += 1
                if got >= need:
                    return i
        return len(order)
    import random
    shuffled = CANDIDATES[:]
    random.Random(0).shuffle(shuffled)       # no gate = you don't know which is which
    gated = fetches_to_target(ranked)
    naive = fetches_to_target(shuffled)
    print(f"{name:24} precision@{k}={p_at_k:.2f}  fetches_to_90%signal: gated={gated} vs naive={naive}  "
          f"({(naive-gated)/naive*100:+.0f}% wasted-fetch cut)")
    return p_at_k


def _keyword_baseline(query, url):
    """Trivial reference scorer so the harness runs before the embedder lands. NOT the gate."""
    import re
    toks = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2]
    u = url.lower()
    return sum(t in u for t in toks)


def _humanize(url):
    """Free pre-fetch 'snippet': turn a URL's host+path into words (no network).
    static embeddings need text, and the URL slug IS text we already have."""
    import re
    from urllib.parse import urlsplit
    sp = urlsplit(url)
    words = re.split(r"[^a-z0-9]+", (sp.netloc + " " + sp.path).lower())
    return " ".join(w for w in words if len(w) > 1 and w not in ("com", "www", "org", "net"))


def make_embed_scorer(with_slug: bool):
    """model2vec potion-retrieval-32M: cosine(query, candidate text). Encode query once."""
    import numpy as np
    from model2vec import StaticModel
    m = StaticModel.from_pretrained("minishlab/potion-retrieval-32M")
    q = m.encode([QUERY])[0]; q = q / np.linalg.norm(q)

    def score(query, url):
        if with_slug == "snippet":
            text = SNIPPETS.get(url, _humanize(url))
        elif with_slug:
            text = f"{url} | {_humanize(url)}"
        else:
            text = url
        v = m.encode([text])[0]
        return float(v @ q / (np.linalg.norm(v) + 1e-9))
    return score


def _keyword_snippet(query, url):
    """Keyword baseline but over the snippet text (fair comparison vs embedder-on-snippet)."""
    import re
    toks = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 2]
    hay = (url + " " + SNIPPETS.get(url, "")).lower()
    return sum(t in hay for t in toks)


if __name__ == "__main__":
    print(f"candidates: {len(SIGNAL)} signal + {len(JUNK)} junk = {len(CANDIDATES)}\n")
    print("-- URL only (what a bare URL list gives you) --")
    evaluate(_keyword_baseline, "keyword (url)")
    evaluate(make_embed_scorer(with_slug=True), "potion-32M (url+slug)")
    print("-- with search snippets (what search/crawl gives you) --")
    evaluate(_keyword_snippet, "keyword (snippet)")
    evaluate(make_embed_scorer(with_slug="snippet"), "potion-32M (snippet)")
