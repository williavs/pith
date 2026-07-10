# pith API reference

Import via `git+https://github.com/williavs/pith.git@master`. All keyless, deterministic, no-LLM,
public-data-only. Return dicts below list the fields you actually get.

## Extras matrix

| Extra | Adds | Needed for |
|---|---|---|
| (base) | extraction, `find_businesses` (OSM/Overpass), news, jobs, financials | most work |
| `[osint]` | `phonenumbers` | `phone_intel` |
| `[email]` | `dnspython` | `verify_email(check_mx=True)` MX deliverability |
| `[js]` | `scrapling` + `curl_cffi` (then `scrapling install` for the browser) | walled/JS sites: LinkedIn, Reddit, Instagram, X, JS-rendered pages |
| `[places]` | `overturemaps` + `duckdb` | the Overture provider in `find_businesses` (bigger coverage) — may need Rust to build |

## Extraction core

- `from pith import Extractor` — `Extractor().extract(urls, render_js="auto", concurrency=1, timeout=None)`
  → `ExtractResult(results=[Result], errors=[{url,error,reason}])`.
  `Result`: `.url .title .markdown .emails .phones .socials .links .addresses .structured .meta .facts
  .error` (per-row soft failure: `empty`/`timeout`/`blocked`/`http_404`/…). Parallel-compat aliases:
  `.excerpts` (`[markdown]`), `.full_content`.
- `await Extractor().aextract(urls, ...)` — same, async (offloaded to a thread; won't block your loop).

## Email / phone validation

- `verify_email(email, check_domain=False, check_mx=False)` →
  `{email, valid_syntax, domain, is_role, is_disposable, is_freemail, has_alias, domain_resolves?, has_mx?}`.
  Offline unless a check flag is set. **No SMTP** (by design — reputation risk). `has_mx=None` if
  `[email]`/dnspython isn't installed.
- `phone_intel(number, region=None)` → `{valid, e164, country_code, region, location, carrier, line_type}`.
  Pass E.164 (`+1…`) or set `region`. `line_type` ∈ mobile/fixed_line/**fixed_or_mobile** (NANP can't
  split)/toll_free/voip/… `pip install pith[osint]`.

## Contact / company

- `contact_evidence(website, workers=4, timeout=20)` → `{domain, facts, coverage, whois, firmographics}`.
  Crawls team/about/contact pages (URL + nav-text, browser-escalates for JS shells). `facts` = list of
  `Fact{value, kind∈email|phone|social|name|address, corroboration, labels, sources}`.
- `contact_evidence_many(websites, site_workers=5, page_workers=4, timeout=20)` → `[ev, …]` in input
  order; a failed site becomes `{website, error}`. Cross-site concurrency.
- `website_intel(url)` → `{framework, builder, modernness_grade (A–F), modernness_score, domain_age_years,
  https, responsive, copyright_year, dated_signals, …}`.
- `enrich_company(name, website, workers=4)` → a flat GTM firmographic row (composed from the above).
- `firmographics(structured)` → `{rating, review_count, hours, priceRange, foundingDate, numberOfEmployees,
  lat, lon, areaServed}` from a business's own schema.org (also returned inside `contact_evidence`).

## Recipes (apply YOUR judgment to evidence)

- `owner_email(facts, prefer=("owner","person","role"))` → best `Fact` (or None).
- `rank_phones(facts, area_code=None, min_corroboration=1)` → `[Fact]`.
- `people(facts, include_third_party=False)` → `[{name, title, emails, rel, methods, corroboration, sources}]`.
- `qualify(contact, require=("email",), max_grade=None)` → bool.
- `accept_identity(corroborations, min_signals=2, exclude_self=True, alias_hosts=True)` → accepted candidates.

## Discovery + signals

- `find_businesses(category, location, sources="auto", limit=100, radius_km=None, has_website=False,
  has_phone=False, min_confidence=0.0)` → `{businesses:[{name,phone,website,email,address,category,lat,lon,
  confidence, providers, corroboration, evidence}], coverage, geo}`. Keyless via OSM/Overpass; add a free
  key (`PITH_YELP_KEY`/`PITH_GOOGLE_KEY`/`PITH_FSQ_KEY`) to light up more providers (they merge).
- `directory_search(category, location, limit=30)` → `[{name, phone, address, website}]` (thin wrapper on
  find_businesses).
- `jobs_search(company, domain, render=True)` → `{ats, token, count, postings:[{title, location, department,
  url, posted}]}`. Discovers Greenhouse/Lever/Ashby/Workday/… or the company's own JobPosting schema.
- `news_search(company, domain=None, qualifier=None, window_days=90)` → `[{title, url, date, source, signal,
  provider, extractable}]`. `signal` ∈ funding/leadership/hiring/product/ai/security/m&a/expansion.
- `company_intel(name, ticker=None)` → `{kind (us_public|private_or_other), sources_used, financials, market,
  filings, peer, funding (Form D raises), facts (Wikidata), identity (GLEIF)}`.

## OSINT (person footprint)

- `enumerate_profiles(handle, workers=25, timeout=10, report=False)` → `{profiles:[{site, url, kind, value}],
  coverage}`. ~480 sites, existence-only. `report=True` includes what couldn't be checked.
- `gravatar_profile(email)` → `{exists, profile_url, display_name, name, location, about, avatar, accounts,
  urls}`.

## CLI

`pith <url>` (one page → markdown) · `pith <url> --format json` · `pith --from list.csv --workers 8`
(batch; CSV rows are `url` or `label,url`) · `pith --sitemap URL --match SUBSTR` · `pith --links HUB_URL --match SUBSTR` (every article a hub/index/TOC links to) · `--llms-txt OUTDIR` on any batch writes a markdown-per-page tree + llms.txt index (auto-prefers native <url>.md). Run `pith --help`.
