"""Decision-maker dig — the real test: how much REAL contact/company info can we pull off a
person, LLM-free, given just a name + company?

The loop pith is the last mile of:
  1. discover   — SearXNG search (free, self-hosted) -> URLs + snippets   [pith doesn't do this]
  2. gate       — rank by relevance, keep top-K under a fetch budget       [pith.cli.gate]
  3. enrich     — fetch the survivors, tiered                              [pith.Extractor]
  4. extract    — deterministic: JSON-LD/schema.org + contact regex        [no LLM, no weights]

Run:  ../.venv/bin/python dm_dig.py "Name" "Company"
"""
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pith import Extractor
from pith.cli import gate

SEARX = "http://ubuntu-homelab:8889/search"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")
SOCIAL = re.compile(r"https?://(?:www\.)?(?:linkedin\.com/(?:in|company)/[\w-]+|(?:twitter|x)\.com/[\w]+|github\.com/[\w-]+)")


def search(q, n=12):
    url = f"{SEARX}?q={urllib.parse.quote(q)}&format=json"
    data = json.load(urllib.request.urlopen(url, timeout=25))
    return [(r["url"], r.get("title", ""), r.get("content", "")) for r in data.get("results", [])[:n]]


def raw_html(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 pith"})
        return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
    except Exception:
        return ""


def json_ld(html):
    """Structured data the page embeds for Google — schema.org Person/Organization etc.
    Deterministic gold: name, jobTitle, worksFor, email, telephone, sameAs (socials)."""
    blocks = []
    for m in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.S):
        try:
            blocks.append(json.loads(m.strip()))
        except Exception:
            pass
    return blocks


def _walk_fields(obj, want=("name", "jobTitle", "email", "telephone", "sameAs", "worksFor", "address", "@type")):
    """Pull interesting schema.org fields out of nested JSON-LD."""
    found = {}
    def rec(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in want and v and not isinstance(v, (dict, list)):
                    found.setdefault(k, v)
                if k == "sameAs" and v:
                    found.setdefault("sameAs", v if isinstance(v, list) else [v])
                rec(v)
        elif isinstance(o, list):
            for x in o:
                rec(x)
    rec(obj)
    return found


def main(name, company):
    query = f"{name} {company}"
    print(f"DIG: {query}\n{'='*66}")
    hits = search(f"{name} {company} LinkedIn contact")
    print(f"1. discover (SearXNG): {len(hits)} results")

    targets = [(None, u) for u, _, _ in hits]
    snippets = {u: f"{t} {c}" for u, t, c in hits}
    ranked = gate(targets, query, budget=6, snippets=snippets)
    print(f"2. gate: keep top {len(ranked)} of {len(targets)} by relevance")

    ex = Extractor()
    emails, phones, socials, structured = set(), set(), set(), []
    for _, url in ranked:
        out = ex.extract([url])
        md = out.results[0].excerpts[0] if out.results else ""
        html = raw_html(url)
        emails |= set(EMAIL.findall(md + " " + html))
        phones |= set(PHONE.findall(md))
        socials |= set(SOCIAL.findall(md + " " + html))
        for block in json_ld(html):
            f = _walk_fields(block)
            if f:
                structured.append((url, f))
        print(f"   fetched {url[:60]:60}  md={len(md)}B")

    print(f"\n3. deterministic extract (no LLM):")
    print(f"   emails:  {sorted(e for e in emails if 'sentry' not in e and 'example' not in e)[:8]}")
    print(f"   phones:  {sorted(phones)[:5]}")
    print(f"   socials: {sorted(socials)[:8]}")
    print(f"   schema.org structured data blocks: {len(structured)}")
    for url, f in structured[:4]:
        keep = {k: v for k, v in f.items() if k in ('name', 'jobTitle', 'email', 'telephone', 'sameAs', '@type')}
        if keep:
            print(f"     [{url[:40]}] {keep}")


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "Matt MacInnis"
    company = sys.argv[2] if len(sys.argv) > 2 else "Rippling"
    main(name, company)
