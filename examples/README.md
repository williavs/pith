# pith examples

Runnable, real-data examples — each is both a demo and the "best way to use this part of the
SDK". Every one hits the real internet (or, where noted, uses crafted inputs on purpose to
show edge-case handling). Install with the extras you need:

```bash
pip install 'pith[js]'      # browser tier (scrapling) + curl_cffi impersonation
pip install 'pith[osint]'   # phone intelligence (phonenumbers)
```

The contact examples follow pith's evidence model: the core returns **Facts** (values with
provenance + corroboration + transparent `email_type`/line-type labels), never a "primary"
pick. The *judgment* — which email to reach, which phones to keep — is the caller's, applied
via `pith.recipes` (`owner_email`, `rank_phones`). The examples show that split in practice.

## gtm/ — sales / go-to-market

| Example | What it teaches | Run |
|---|---|---|
| **gtm/build_sales_list.py** | Build a list from a market: `directory_search` → `website_intel` (A–F grade) → `contact_evidence` + `recipes.owner_email`/`rank_phones`. Ranked JSON. | `python examples/gtm/build_sales_list.py "plumbers" "Tulsa, OK" 8` |
| **gtm/enrich_list.py** | Enrich a list you already hold: `enrich_company` → firmographics, company-matched emails, socials, tech grade. CSV/JSON. | `python examples/gtm/enrich_list.py stripe.com https://linear.app` |
| **gtm/companies.csv** | Sample list input for the `pith --from` CLI. | `pith --from examples/gtm/companies.csv --format table` |
| **scout/** | The same pipeline as a live browser console with SSE observability (a full demo app). | `python examples/scout/server.py` → localhost:8848 |

## osint/ — people research

| Example | What it teaches | Run |
|---|---|---|
| **osint/investigate.py** | The investigation waterfall: `verify_email` → `gravatar_profile` (email→accounts) → `enumerate_profiles` (footprint + coverage) → phone intel. All public + deterministic. | `python examples/osint/investigate.py beau@dentedreality.com.au` |

## tooling/ — see the actual data

| Example | What it teaches | Run |
|---|---|---|
| **tooling/datatables/gen.py** | Runs every extractor across a normal + edge-case matrix and renders sortable browser tables — so you can SEE the real output, including false-positive handling and failure rows. | `python examples/tooling/datatables/gen.py` → open `tooling/datatables/index.html` |

## personas/ — end-to-end, in one operator's voice

Each subfolder is a real-world persona (SDR, agency-founder, investigator, journalist,
recruiter, security-researcher) with a README + a runnable build script or written artifact —
the SDK used the way that role would actually use it.

| Persona | Run |
|---|---|
| **personas/sdr/build_leads.py** | `python examples/personas/sdr/build_leads.py` |
| **personas/agency-founder/build.py** | `python examples/personas/agency-founder/build.py` |

## The SDK in three lines

```python
from pith import Extractor
out = Extractor().extract(["https://example.com"], concurrency=8)   # tiered fetch hidden
for r in out.results:
    print(r.title, r.emails, r.phones, r.socials, r.structured)      # deterministic, no LLM
```

Everything else — `contact_evidence` (+ `pith.recipes`), `website_intel`, `enrich_company`,
`directory_search`, `enumerate_profiles`, `gravatar_profile`, `phone_intel`, `verify_email` —
is a one-call function returning plain data. Or run `python -m pith.serve` and hit the same
capabilities over HTTP from any language.
