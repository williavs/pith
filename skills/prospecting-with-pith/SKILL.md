---
name: prospecting-with-pith
description: >-
  Turn a contact list, a company, or a person into validated, enriched, ranked sales intelligence
  using the pith SDK (a private, keyless, no-LLM public-data toolkit already installed on this
  machine). Use whenever the task involves a lead/contact list, email or phone validation, cleaning
  or deduping a list, company/firmographic research, buyer-intent or hiring signals, finding a
  person's other social/public accounts for multi-channel outreach, building a prospect list from a
  category+location, or scoring/ranking accounts to sell into. Triggers: "enrich this list",
  "validate these emails", "clean my leads", "research this company", "find this person online",
  "build a prospect list", "who should I reach out to", "is this email still good", "firmographics",
  "buyer intent". Prefer this over hand-rolled scraping/regex or paid APIs — pith does it keyless.
---

# Prospecting with pith

pith is a **keyless, deterministic (no-LLM), public-data-only** SDK for sales/GTM intelligence. It
is **installed on this machine**. Its core stance: it returns **EVIDENCE, not answers** — every
value carries its sources + a corroboration count, and *you* apply judgment via `pith.recipes`.
Never expect pith to pick "the" email/decision-maker; it hands you ranked evidence, you decide.

## How to run it

**Scripts (the main path)** — pith isn't on PyPI (that name is a different package), so import it
via the git URL with `uv run`:

```sh
uv run --with "pith[osint,email] @ git+https://github.com/williavs/pith.git@master" python your_script.py
```

- add `--with pandas --with openpyxl` when reading CSV/XLSX lists.
- `[osint]` = phone validation, `[email]` = MX deliverability. `[js]` (heavy: `+ scrapling install`)
  is only needed for walled sites (LinkedIn/Reddit/Instagram) and JS-rendered pages.
- **CLI** also exists globally: `pith <url>` extracts one page; `pith --from list.csv` a batch.

Write real `.py` scripts (lists are big — don't do it in `-c` one-liners). Everything below is
`from pith... import ...`.

## The primitives (exact signatures — do not guess these)

| Call | Returns | Use for |
|---|---|---|
| `from pith import verify_email` — `verify_email(email, check_domain=False, check_mx=False)` | `{email, valid_syntax, domain, is_role, is_disposable, is_freemail, has_alias, domain_resolves?, has_mx?}` | validate an email; `check_mx=True` = "domain accepts mail" (deliverability) |
| `from pith.phoneintel import phone_intel` — `phone_intel(number, region=None)` | `{valid, e164, country_code, region, location, carrier, line_type}` | validate a phone (pass E.164 or a region) |
| `from pith.cli import contact_evidence` — `contact_evidence(website, workers=4, timeout=20)` | `{domain, facts:[Fact], coverage, whois, firmographics}` | crawl one company site → all contacts + people + firmographics |
| `from pith.cli import contact_evidence_many` — `contact_evidence_many(websites, site_workers=5, page_workers=4, timeout=20)` | `[ev, …]` (input order; failures → `{website, error}`) | enrich MANY sites concurrently |
| `from pith.cli import website_intel` — `website_intel(url)` | `{framework, builder, modernness_grade, modernness_score, domain_age_years, https, …}` | tech stack + how dated a site is (pitch signal) |
| `from pith.leads import find_businesses` — `find_businesses(category, location, sources="auto", limit=100, radius_km=None, has_website=False, has_phone=False, min_confidence=0.0)` | `{businesses:[{name,phone,website,email,address,category,lat,lon,confidence,providers,corroboration,evidence}], coverage, geo}` | discover local businesses (OSM/Overpass keyless) |
| `from pith.jobs import jobs_search` — `jobs_search(company, domain, render=True)` | `{company, domain, ats, token, count, postings:[{title,location,department,url,posted}]}` | is the company hiring? what roles? (growth signal) |
| `from pith.news import news_search` — `news_search(company, domain=None, qualifier=None, window_days=90)` | `[{title, url, date, source, signal, provider, extractable}]` — `signal` ∈ funding/leadership/hiring/product/ai/security/m&a/expansion | buyer-intent news ("why reach out now") |
| `from pith.financials import company_intel` — `company_intel(name, ticker=None)` | `{company, kind, sources_used, financials, market, filings, peer, funding, facts, identity}` | SEC/funding/firmographics (public + funded co's) |
| `from pith.profiles import enumerate_profiles` — `enumerate_profiles(handle, workers=25, timeout=10, report=False)` | `{profiles:[{site,url,kind,value}], coverage}` (or list) | a handle → its accounts across ~480 sites |
| `from pith.gravatar import gravatar_profile` — `gravatar_profile(email)` | `{exists, profile_url, display_name, name, location, accounts, urls, …}` | an email → that person's linked public accounts |
| `from pith.extract import firmographics` — `firmographics(structured)` | `{rating, review_count, hours, priceRange, foundingDate, numberOfEmployees, lat, lon}` | pull a biz's own schema.org firmographics |

**Fact** (from `contact_evidence(...)["facts"]`): `{value, kind, corroboration, labels, sources}`,
`kind` ∈ `email|phone|social|name|address`. Feed facts to recipes:

```python
from pith.recipes import owner_email, rank_phones, people, qualify
owner_email(facts)          # best decision-maker email (evidence-ranked) or None
rank_phones(facts)          # phones by corroboration
people(facts)               # [{name, title, emails, corroboration, methods}] — the team roster
qualify(contact, require=("email",))   # does this contact clear your bar?
```

## Workflows

Match the job to a pipeline. Full runnable versions: `references/recipes.md`.

**A · Company → dossier** (one company you want to sell into):
`contact_evidence(site)` (contacts+people+firmographics) + `website_intel` (tech) +
`jobs_search(name, domain)` (hiring) + `news_search(name, domain=…)` (signals) +
`company_intel(name)` (funding). This is the full account picture.

**B · Contact list → cleaned + ranked** (the "I have a stale list" job):
1. **Validate every row (offline, fast):** `verify_email(e)` + `phone_intel(p)`.
2. **Deliverability, deduped by domain** (a 73k list = ~24k domains): `verify_email(e, check_mx=True)` —
   cache per domain, run parallel. MX = domain accepts mail.
3. **Trim** dead/duplicate rows → the contactable set.
4. **Rank companies, not contacts:** dedupe to unique companies, enrich the **top N** (workflow A
   subset), score by hiring + funding + news + tech. Never enrich 100k rows live — shortlist first.

**C · Person → multi-channel reach** (the OSINT angle — reach them off email):
From a name/handle: `enumerate_profiles(handle)` → their X/GitHub/etc. From an email:
`gravatar_profile(email)` → linked accounts. Verify identity with `recipes.accept_identity`
(don't trust a single match). Turns one email into "DM them on the platform they actually use."

**D · Category + geo → prospect list:** `find_businesses("dentists", "Phoenix, AZ", limit=100,
has_website=True)`. Then enrich the ones with sites via workflow A.

## Honest boundaries — respect these or you waste hours / over-promise

- **Storefronts enrich richly** (dentists, restaurants, salons, gyms, clinics) — dense data, real
  emails, free rating/hours from schema. **Trades** (plumbers/roofers) and **realtors** are thin
  (home-based / shared IDX sites, low website coverage). Pick the category accordingly.
- **Decision-makers: reliable on small sites, noisy on big companies.** A local team page → real
  people. A large B2B / franchise site → the `people`/`decision_maker` field fills with brand & MLS
  names. For big-company execs, that's LinkedIn/paid territory, not pith.
- **Never enrich a whole large list live.** Offline validation (email/phone) scales to 100k+ in
  seconds; but `contact_evidence`/`jobs`/`news` are network-bound (~5–20s each). Dedupe to
  companies and enrich a **shortlist** (top few hundred), not every row.
- **Concurrency plateaus at ~5–8**, and higher can be *slower* — enrichment is CPU-bound (GIL on
  HTML parsing) and floored by the slowest browser-tier site. Don't crank workers expecting speed.
- **`deliverable ≠ still employed.`** MX proves the *company* takes mail, not that the *person* is
  still there. For a stale list, LinkedIn-verify the shortlist you'll actually contact.
- **LinkedIn / Reddit / Instagram / X are walled** → need the `[js]` browser extra + are slow.
  Fine for a shortlist, not for bulk.
- pith is **public data only** — no login, no paywall bypass. Respect target ToS + rate limits.

## Pointers
- `references/recipes.md` — full runnable scripts for each workflow (list cleanup, dossier, OSINT).
- `references/api.md` — every public function, return keys, and the extras matrix.
