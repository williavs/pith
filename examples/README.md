# pith examples

Runnable, real-data examples — each is both a demo and the "best way to use this part of the
SDK". Every one hits the real internet (or, where noted, uses crafted inputs on purpose to
show edge-case handling). Install with the extras you need:

```bash
pip install 'pith[js]'      # browser tier (scrapling) + curl_cffi impersonation
pip install 'pith[osint]'   # phone intelligence (phonenumbers)
```

## Sales / GTM

| Example | What it teaches | Run |
|---|---|---|
| **build_sales_list.py** | Build a list from a market: `directory_search` → `website_intel` (A–F grade) → `find_contact` (owner email/phone). Ranked JSON. | `python examples/build_sales_list.py "plumbers" "Tulsa, OK" 8` |
| **enrich_list.py** | Enrich a list you already hold: `enrich_company` → firmographics, company-matched emails, socials, tech grade. CSV/JSON. | `python examples/enrich_list.py stripe.com https://linear.app` |
| **scout/** | The same pipeline as a live browser console with SSE observability (a full demo app). | `python examples/scout/server.py` → localhost:8848 |

## OSINT / people research

| Example | What it teaches | Run |
|---|---|---|
| **investigate.py** | The investigation waterfall: `verify_email` → `gravatar_profile` (email→accounts) → `enumerate_profiles` (footprint + coverage) → phone intel. All public + deterministic. | `python examples/investigate.py beau@dentedreality.com.au` |

## See the actual data

| Example | What it teaches | Run |
|---|---|---|
| **datatables/gen.py** | Runs every extractor across a normal + edge-case matrix and renders sortable browser tables — so you can SEE the real output, including false-positive handling and failure rows. | `python examples/datatables/gen.py` → open `datatables/index.html` |

## The SDK in three lines

```python
from pith import Extractor
out = Extractor().extract(["https://example.com"], concurrency=8)   # tiered fetch hidden
for r in out.results:
    print(r.title, r.emails, r.phones, r.socials, r.structured)      # deterministic, no LLM
```

Everything else — `find_contact`, `website_intel`, `directory_search`, `enumerate_profiles`,
`gravatar_profile`, `phone_intel`, `verify_email` — is a one-call function returning a plain
dict. Or run `python -m pith.serve` and hit the same capabilities over HTTP from any language.
