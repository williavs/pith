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

out = ex.extract(urls=["https://www.crunchbase.com/organization/stripe"], concurrency=8)
for r in out.results:
    print(r.title, r.publish_date)
    print(r.excerpts[0])          # clean markdown
    print(r.emails, r.socials)    # deterministic structured data — no LLM
    print(r.structured)           # schema.org Person/Organization entities
```

`extract()` params: `urls`, `full_content` (False), `render_js` (`"auto"` | `True` |
`False`), `concurrency` (1). Result fields: `r.url`, `r.title`, `r.publish_date`,
`r.excerpts` (list), `r.full_content`, plus auto-extracted `r.emails`, `r.phones`,
`r.socials`, `r.structured`, `r.meta`.

## Use — CLI

```sh
pith "https://example.com/article"

# a list of URLs (one per line, bare URL or `label,url`; # and blanks skipped)
pith --from companies.csv                 # markdown, per-label sections (default)
pith --from companies.csv --format table  # compact: status / bytes / target
pith --from companies.csv --format json   # machine-readable {results, errors}
pith --from companies.csv --workers 8     # parallel fetches
```

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
