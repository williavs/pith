"""List-enricher throughput — the sales fast path, optimized.

The real job: a rep drops in a contact list (name, company, website) and wants every
company site enriched, fast. Company sites are normal pages = pith's cheap tier, which
scales wide. This measures records/sec across concurrency levels to find the sweet spot
and prove the library-level parallelism (Extractor.extract(concurrency=N)) is worth it.

Run:  ../.venv/bin/python enrich_throughput.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pith import Extractor

# a realistic contact-list column of company websites — all normal pages (cheap tier)
SITES = [
    "https://stripe.com", "https://www.anthropic.com", "https://linear.app",
    "https://vercel.com", "https://www.notion.so", "https://www.figma.com",
    "https://www.datadoghq.com", "https://www.cloudflare.com", "https://www.twilio.com",
    "https://www.atlassian.com", "https://www.hashicorp.com", "https://www.mongodb.com",
    "https://www.snowflake.com", "https://www.databricks.com", "https://www.gitlab.com",
    "https://www.elastic.co", "https://www.confluent.io", "https://www.okta.com",
    "https://www.zoom.us", "https://www.dropbox.com", "https://www.asana.com",
    "https://www.shopify.com", "https://www.squarespace.com", "https://www.hubspot.com",
]


def main():
    ex = Extractor()
    print(f"enriching {len(SITES)} company websites (cheap tier) — records/sec by concurrency\n")
    print(f"{'concurrency':>11} {'wall-clock':>11} {'rec/sec':>9} {'ok':>5} {'speedup':>8}")
    base = None
    for c in [1, 4, 8, 16, 24]:
        t = time.perf_counter()
        out = ex.extract(SITES, render_js=False, concurrency=c)  # render_js=False: pure cheap tier, no browser
        dt = time.perf_counter() - t
        rps = len(SITES) / dt
        if base is None:
            base = dt
        print(f"{c:>11} {dt:>10.1f}s {rps:>9.1f} {len(out.results):>5} {base/dt:>7.1f}x")


if __name__ == "__main__":
    main()
