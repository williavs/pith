# pith

Turn any public URL into clean, LLM-ready markdown. A **free, drop-in replacement for the
[Parallel Extract API](https://docs.parallel.ai)** — same call shape, same result fields, $0.

It's the extraction stage of a pipeline: URL in → clean markdown out. Normal pages go through
a fast HTTP path; JS-rendered and bot-protected pages (Reddit, LinkedIn, Instagram, X, and the
B2B sources below) go through a real stealth browser to reach the **public** content.

## Install

From this repo (not PyPI — the `pith` name there is an unrelated package):

```sh
# base — clean markdown from normal/public pages, no browser
pip install "pith @ git+https://github.com/williavs/pith"

# + walled / JS-rendered sites (Reddit, LinkedIn, Instagram, X, B2B sources) — what you'll want
pip install "pith[js] @ git+https://github.com/williavs/pith"
scrapling install          # one-time: downloads the stealth browser (~a few hundred MB)

# + documents (PDF, Word, PowerPoint, Excel, epub, images) → markdown via MarkItDown
pip install "pith[docs] @ git+https://github.com/williavs/pith"
```

Python 3.10+ (developed and tested on 3.13).

## Use — Python (mirrors Parallel's API)

```python
from pith import Extractor

ex = Extractor()  # no API key, no LLM

out = ex.extract(urls=["https://www.crunchbase.com/organization/stripe"], concurrency=8, timeout=15)
for r in out.results:
    print(r.title, r.publish_date)
    print(r.markdown)             # clean markdown (also as r.excerpts[0] / r.full_content — Parallel shape)
    print(r.emails, r.socials)    # deterministic structured data — no LLM
    print(r.structured)           # list[dict] of schema.org entities (Person/Organization)
    if r.error:                   # per-row soft failure: "empty" | "timeout" | "blocked" | "http_404" | ...
        print("incomplete:", r.error)
```

**`extract()` params:** `urls`, `render_js` (`"auto"` | `True` | `False`), `concurrency` (1),
`timeout` (seconds, per URL — each fetch tier honors it; `None` = 12s default).

**Result fields:** `r.url`, `r.title`, `r.publish_date`, `r.markdown` (canonical clean markdown),
`r.error` (per-row failure reason, or `None`), plus auto-extracted `r.emails`, `r.phones`,
`r.socials` (profile links matched against a ~480-site list, not just the big five),
`r.addresses`, `r.structured` (`list[dict]` — schema.org entities, kept **whole**: not just
name/title but `rating`/`hours`/`priceRange`/`foundingDate`/`numberOfEmployees`/`geo` when the
page publishes them), `r.meta` (**every** OpenGraph/Twitter/meta tag, incl. `business:contact_data:*`).
pith surfaces the raw data and labels it; you filter — it doesn't pre-drop.

**Parallel-compat aliases:** `r.excerpts` (`[r.markdown]`) and `r.full_content` (`r.markdown`) —
so a Parallel Extract mapping ports unchanged.

**Async:** `await ex.aextract(urls, ...)` — same args, offloaded to a worker thread so your
event loop stays free (FastAPI/async apps). No need to wrap it in `asyncio.to_thread` yourself.

**Per-URL failures:** a URL that fetches but yields nothing comes back in `results` with
`r.error` set; a URL that raises comes back in `out.errors` as `{url, error, reason}`, where
`reason` is the same stable set (`timeout`/`blocked`/`http_404`/`dns`/...). Failures never sink the batch.

## Use — CLI

```sh
pith "https://example.com/article"

# a list of URLs (one per line, bare URL or `label,url`; # and blanks skipped)
pith --from companies.csv                 # markdown, per-label sections (default)
pith --from companies.csv --format table  # compact: status / bytes / target
pith --from companies.csv --format json   # machine-readable {results, errors}
pith --from companies.csv --workers 8     # parallel fetches

# a whole site -> agent-ready corpus (markdown-per-page tree + llms.txt index)
pith --sitemap https://example.com/sitemap.xml --limit 500 --llms-txt ./example-docs
pith --crawl https://example.com --limit 200 --llms-txt ./example-docs   # no sitemap? crawl
```

`--llms-txt` makes any HTML-only site agent-friendly, keyless — see `examples/llms-txt/`.

## Business intelligence — leads, people, signals

Beyond single-URL extraction, pith has a keyless business-data layer built on the same
evidence model (values carry their sources + corroboration, never a hidden score).

**One call, the whole company.** `contact_evidence` crawls a site's key pages (team/about/contact,
discovered by URL *and* nav text, with a browser fallback for JS navs) and folds every source
together — text, schema.org, OpenGraph, Cloudflare-obfuscated, and WHOIS:

```python
from pith.cli import contact_evidence
from pith.recipes import owner_email, people

ev = contact_evidence("https://arizonabiltmoredentistry.com")   # no key, no LLM
owner_email(ev["facts"])        # -> best contact email (evidence-ranked, you apply the judgment)
people(ev["facts"])             # -> decision-makers: [{name, title, emails, corroboration}]
ev["firmographics"]             # -> {'rating': '5.0', 'review_count': '4', 'hours': 'Mo-Th 06:00-18:00',
                                #     'priceRange': '$', 'lat': ..., 'lon': ...}   ← free, from the site's own schema
ev["facts"]                     # -> every email/phone/social/address as a Fact(value, sources, corroboration)
```

**Discover, then enrich.**

```python
from pith.leads import find_businesses
res = find_businesses("dentists", "Phoenix, AZ", limit=100)   # OSM/Overpass + Overture, keyless
for b in res["businesses"]:
    print(b["confidence"], b["providers"], b["name"], b["phone"], b["website"])
```

- **`pith.cli.contact_evidence(website)`** — one call → contacts + decision-makers + firmographics
  (rating/hours/founded/employees/geo) + socials, all as sourced evidence. Apply `pith.recipes`
  (`owner_email`, `rank_phones`, `people`) with your own intent on top — pith never picks for you.
- **`pith.leads.find_businesses(category, location, ...)`** — multi-source local-business
  discovery. Providers: **Overpass** (OSM, live) + **Overture** (bulk, needs `pith[places]`)
  keyless out of the box; **Yelp / Google / Foursquare** light up when you set a free key
  (`PITH_YELP_KEY` etc.). Results are **waterfall-merged** across sources: each field becomes a
  `Fact` whose corroboration = how many providers agree, blended into a confidence score. This is
  what `directory_search` now runs on (the old YellowPages/SuperPages scraper is gone).
- **`pith.people.extract_people(text, emails, url)`** — deterministic decision-maker extraction
  (name + title + email) from team/about-page HTML, not just schema.org. Folded into
  `contact_evidence`; surfaced via `recipes.people`.
- **`pith.jobs.jobs_search` / `pith.news.news_search` / `pith.financials.company_intel`** —
  hiring, buyer-intent news, and SEC/funding signals per company (all keyless).

Two runnable Streamlit workbenches show the whole thing: **`examples/leadgen`** (local SMB lists →
enrich → CSV) and **`examples/b2b`** (paste account domains → hiring/news/tech/funding dossier with
a payroll/AI lens). Measured coverage + the free-vs-paid gap analysis: `benchmarks/LEADS_COVERAGE.md`,
`benchmarks/REQUIREMENTS_GAPS.md`.

## Supported sources

Tested live against real public URLs (see `benchmarks/`). pith returns **public data only** —
it does not log in, bypass auth, or defeat paywalls.

**✅ Full public content**

| source | what you get | path |
|---|---|---|
| Reddit | posts, comments | browser |
| LinkedIn (company + person) | posts, headline, about, experience, education¹ | browser |
| X / Twitter | tweet text | browser |
| Medium | article content | browser |
| Crunchbase | funding, firmographics | browser |
| Indeed | open roles (hiring intent)² | browser |
| Product Hunt | launches | browser |
| Trustpilot | reviews + rating | browser |
| Glassdoor | company overview | browser |
| arXiv, GitHub | public pages | fast HTTP |
| Guardian, BBC, Substack, FT (sections) | article / section content | fast HTTP |
| WSJ (free/section pages) | article text | impersonation tier |
| PDF / Word / PowerPoint / Excel / epub | document text → markdown | MarkItDown (`[docs]`) |

**🟡 Partial** — identity/metadata, body behind a login wall or flaky:

| source | what you get |
|---|---|
| Instagram | bio + captions — usually full, occasionally hits a login wall² |
| Facebook | name + follower counts; post body is login-walled |
| Threads | short post captions only |

**❌ Not supported** — hard paywall / anti-bot, body not reachable:

| source | why |
|---|---|
| NYTimes (article body), Bloomberg, WSJ | paywall + CAPTCHA block the body. pith does not defeat paywalls. |

¹ LinkedIn person pages also include a "sign in to view full profile" notice; the public
fields above still come through.
² Indeed and Instagram occasionally serve an anti-bot wall on a given fetch; pith retries
once automatically, but a hard wall on both attempts returns thin/partial content.

## How it works

1. **Fetch** — three tiers, cheapest first. Plain HTTP (`trafilatura`) for normal pages; if
   that 403s or comes back thin, **browser-TLS impersonation** (`curl_cffi`) — ~250 ms, rescues
   sites that fingerprint the TLS handshake but still serve real HTML (WSJ et al.); if *that's*
   still thin, the **stealth browser** (`scrapling`, Cloudflare-solve + Google referer, ~3–8 s).
   The walled sources above skip straight to the browser. Non-HTML documents (PDF/Office/epub)
   go through **MarkItDown** instead of trafilatura.
2. **Clean markdown** — `trafilatura` strips boilerplate (nav, ads, language switchers) and
   emits markdown with links preserved.
3. **Structured data (deterministic, no LLM)** — emails, phones, socials, schema.org
   Person/Organization (JSON-LD), and OpenGraph meta are pulled off the page and returned on
   every result (`r.emails`, `r.socials`, `r.structured`, …). Any semantic step is the
   consuming app's job — pith ships no LLM.

Why a browser at all: Reddit/LinkedIn/Instagram/X block plain HTTP at the TLS-fingerprint /
"network security" layer — `requests`, `curl`, browser-TLS-impersonation (`curl_cffi`), and
the old `.json` endpoints all get 403, even from a clean residential IP. Only a real browser
loading the human HTML page gets through. (The "no auth needed, just hit `.json`" Reddit
tricks floating around are dead as of mid-2026.)

## Dependencies (honest)

| extra | pulls in | notes |
|---|---|---|
| base | `trafilatura` (+ lxml, etc.) | pure pip, no system deps |
| `[js]` | `scrapling[fetchers]` → patchright/playwright + a stealth browser; `curl_cffi` for the impersonation tier | `scrapling install` downloads a browser (~hundreds of MB). Heavy, but it's what beats the walls. |
| `[docs]` | `markitdown[all]` | PDF/Word/PowerPoint/Excel/epub/images → markdown |
| `[pdf]` | `pymupdf` | lighter than `[docs]` if PDFs are all you need |
| `[places]` | `overturemaps` + `duckdb` | bulk business datasets for `pith.leads` (Overture + Foursquare-Open). The Overpass/OSM provider needs none of this — it's live + stdlib-only. |
| `[osint]` | `phonenumbers` | offline phone intelligence (`phone_intel`) |

**Deploying `[js]` (Docker / serverless):** the stealth browser is downloaded by `scrapling
install`, *not* bundled in the wheel — so `pip install` alone won't render JS pages in a fresh
container. In your build phase, after the pip install, run `scrapling install` and set
`PLAYWRIGHT_BROWSERS_PATH` to a path that persists into the runtime image (or leave it default
and make sure the browser dir is copied into the final layer). Skip this only if you run
base-tier extraction (no `render_js=True`, no walled sources).

## Limits & responsible use

- **Public data only.** No login, no auth bypass, no paywall defeat (hard paywalls stay blocked — that's by design).
- **Respect each site's Terms of Service and `robots.txt`.** You are responsible for how you use it.
- The stealth browser presents as a normal browser; keep request rates reasonable.
- Walled sites change defenses over time — the live test suite (`tests/test_live.py`, run `pytest -m live`) is the canary that flags when a method stops working.

## Testing

```sh
pytest -m "not live"   # fast offline unit tests (routing, parsing) — no network
pytest -m live         # hits the real walled sites; the canary for changed defenses
python benchmarks/source_coverage.py   # full per-source coverage run
```

## Why this exists

The paid Extract API is a thin wrapper around: a scraper + a boilerplate stripper + one
optional LLM call. All three are free. This is that, packaged.

## Credits

Profile-enumeration site data (`pith/osint_sites.json`) is vendored from the [Sherlock Project](https://github.com/sherlock-project/sherlock) (MIT). Disposable-email list from [umuterturk/email-verifier](https://github.com/umuterturk/email-verifier) (MIT). pith reimplements the check logic; it does not depend on those packages.

## Agent skill (Claude Code)

`skills/prospecting-with-pith/` is a Claude Code skill that teaches an agent to use pith for
sales-intelligence work — validating/cleaning contact lists, company dossiers, ranking accounts,
and OSINT multi-channel reach — with the exact API and the honest boundaries. Copy it to
`~/.claude/skills/` (or it's picked up automatically if this repo's skills dir is on your skill path).
