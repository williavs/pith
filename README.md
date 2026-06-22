# pith

Turn any public URL into clean, LLM-ready markdown. A **free, drop-in replacement for the
[Parallel Extract API](https://docs.parallel.ai)** — same call shape, same result fields, $0.

It's the extraction stage of a pipeline: URL in → clean markdown out. Handles JS-rendered and
bot-protected pages (Reddit, LinkedIn, …) via a real stealth browser.

## Install

```sh
pip install pith                 # base: clean markdown from normal pages
pip install 'pith[js]'           # + JS-rendered / bot-protected pages
scrapling install                      #   one-time: downloads the stealth browser
pip install 'pith[pdf]'          # + PDFs
```

## Use — Python (mirrors Parallel's API)

```python
from pith import Extractor

ex = Extractor()  # no API key needed for markdown

out = ex.extract(
    urls=["https://www.un.org/en/about-us/history-of-the-un"],
    objective="When was the United Nations established?",  # optional → focused excerpts
)
for r in out.results:
    print(r.title, r.publish_date)
    for excerpt in r.excerpts:
        print(excerpt)
```

`extract()` parameters:
| param | default | meaning |
|---|---|---|
| `urls` | — | list of URLs |
| `objective` | `None` | if set, returns only the passages answering it (one free LLM call) |
| `full_content` | `False` | also return the full page markdown in `r.full_content` |
| `render_js` | `"auto"` | `"auto"` tries static then falls back to a browser if the page looks JS-rendered; `True` forces the browser; `False` never uses it |

Result fields (same as Parallel): `r.url`, `r.title`, `r.publish_date`, `r.excerpts` (list), `r.full_content`.

## Use — CLI

```sh
pith "https://example.com/article"
pith "https://example.com/article" "what is the refund policy?"
pith "https://www.reddit.com/r/python/" --js
```

### A list of URLs

Give pith a file instead of a single URL — one target per line, a bare URL or a
`label,url` pair (csv, either order; `#` and blanks skipped):

```sh
pith --from companies.csv                  # markdown, per-label sections (default)
pith --from companies.csv --format table   # compact: status / bytes / target + summary
pith --from companies.csv --format json    # machine-readable {results, errors}
pith --from companies.csv --workers 8       # parallel fetches
```

Progress prints to stderr, so `--format json > out.json` stays clean. One bad URL is
reported in `errors`, never sinks the batch. See `examples/companies.csv`.

## Social / bot-protected sites

Reddit, LinkedIn, and Instagram hard-block plain HTTP at the edge (TLS-fingerprint /
"network security" walls — `.json` APIs and `requests`/`curl` all get 403, even with
browser-impersonated TLS). pith routes these through the stealth browser
automatically (no `render_js` needed) and gets the **public** content:

| site | works on | what you get |
|---|---|---|
| Reddit | subreddits, posts | titles, post text, comments |
| LinkedIn | public company & person pages | headline, about, experience, education, posts |
| Instagram | public profiles & posts | bio, captions |

Public data only — anything behind a login wall isn't returned (LinkedIn person pages
include a "sign in to view full profile" notice; the public fields above still come through).
Needs the `[js]` extra + `scrapling install`.

## How it works (the whole thing)

1. **Fetch** — `trafilatura` for normal pages (fast, no browser); a **stealth browser** (`scrapling`, with Cloudflare-challenge solving + a Google referer) for JS-rendered and bot-protected pages. Reddit/LinkedIn/Instagram always use the browser.
2. **Clean markdown** — `trafilatura` strips boilerplate (nav, ads, language switchers) and emits markdown with links preserved. Often *cleaner* than the paid API, which leaves that junk in.
3. **Excerpts (optional)** — one call to any OpenAI-compatible model (Groq free tier by default) returns the passages that answer your `objective`. This is also what cleans up social-page noise (sign-in modals, etc.) down to the data you want.

No API key for the markdown. For excerpts, set `GROQ_API_KEY` (free at console.groq.com) or pass
`Extractor(llm_api_key=..., llm_base_url=..., llm_model=...)` to point at any provider.

## Why this exists

The paid Extract API is a thin wrapper around: a scraper + a boilerplate stripper + one optional LLM call.
All three are free. This is that, packaged.
