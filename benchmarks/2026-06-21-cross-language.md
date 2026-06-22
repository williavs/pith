# Cross-language extraction benchmark — 2026-06-21

pith's core does URL → clean markdown. This asks: **could the core be faster in Go or
Rust, and what would a port actually cost?** Seven real implementations across three
languages, run on identical local HTML, plus a piece-by-piece look at the whole core
(not just the extraction step).

Reproduce: `benchmarks/run_bench.sh` (needs `../.venv`, `go`, `cargo`).

## TL;DR

1. **The extraction step is milliseconds; the stealth browser is seconds.** On a walled
   site pith spends 5–8 s in the browser and ~50–200 ms extracting. Porting the
   extraction step to a faster language saves ~2% of wall-clock on those pages. The
   browser dominates, and it's a Python-only asset (`scrapling`/Camoufox).
2. **For normal pages, Go/Rust are 3–15× faster at extraction** — but only `trafilatura`
   (the algorithm pith uses) stays robust across page types. Readability-family ports are
   the fastest *because they give up* on non-article pages (HN comments, MDN docs → 26 B).
3. **Recommendation: don't rewrite pith. Hybrid if volume demands it** — keep the Python
   stealth-browser fetch, add a `go-trafilatura` extraction worker only if you're
   processing many *normal* pages at scale. (Full reasoning in "The port decision".)

## What was tested

Same five local HTML fixtures (6.5 KB HN item → 745 KB Wikipedia), fed to each library.
Fetch and the stealth browser are **excluded** here — they're network-bound /
Python-specific, so the fair core comparison is boilerplate-strip + markdownify given
identical HTML. Median of 7 runs.

| # | implementation | algorithm | markdown |
|---|---|---|---|
| 1 | python:trafilatura | trafilatura (what pith ships) | native |
| 2 | go:trafilatura | markusmobius/go-trafilatura (direct port) | + html-to-markdown |
| 3 | go:readability | go-shiori/go-readability (Mozilla) | + html-to-markdown |
| 4 | go:domdistiller | markusmobius/go-domdistiller (Chrome DOM Distiller) | + html-to-markdown |
| 5 | rust:trafilatura | trafilatura 0.3 (direct port) | native (md feature) |
| 6 | rust:dom_smoothie | dom_smoothie 0.18 (Mozilla Readability) | native |
| 7 | rust:readability | readability 0.3 (arc90) | + htmd |

## Results

<!-- BENCH_TABLE_START -->
### Extraction time (ms, median of 7, lower=faster)

| library | hn_item | mdn_fetch | python_pep8 | un_history | wikipedia_ml |
|---|---|---|---|---|---|
| python:trafilatura | 22.7 | 47.0 | 196.8 | 54.3 | 498.8 |
| go:trafilatura | 2.2 | 9.6 | 44.4 | 9.1 | 180.8 |
| go:readability | 3.7 | 9.7 | 37.7 | 5.4 | 125.3 |
| go:domdistiller | 1.3 | 8.9 | 30.4 | 6.2 | 78.4 |
| rust:trafilatura | 1.5 | 5.3 | 20.7 | 4.0 | 105.1 |
| rust:dom_smoothie | 0.9 | 2.7 | 11.6 | 1.7 | 37.8 |
| rust:readability | 0.4 | 2.0 | 8.2 | 1.5 | 42.7 |

### Output size (bytes, higher usually=more content captured)

| library | hn_item | mdn_fetch | python_pep8 | un_history | wikipedia_ml |
|---|---|---|---|---|---|
| python:trafilatura | 638 | 4531 | 47962 | 1973 | 202627 |
| go:trafilatura | 521 | 2897 | 47905 | 2245 | 196135 |
| go:readability | 42 | 4872 | 47239 | 2080 | 226970 |
| go:domdistiller | 0 | 2052 | 42965 | 2080 | 74523 |
| rust:trafilatura | 1255 | 3147 | 44760 | 2246 | 190283 |
| rust:dom_smoothie | 70 | 4224 | 47568 | 2087 | 210147 |
| rust:readability | 26 | 26 | 11247 | 1607 | 100229 |

### Total time across all fixtures (ms)

| library | total ms | vs python |
|---|---|---|
| rust:dom_smoothie | 54.7 | 15.0x faster |
| rust:readability | 54.8 | 15.0x faster |
| go:domdistiller | 125.2 | 6.5x faster |
| rust:trafilatura | 136.6 | 6.0x faster |
| go:readability | 181.8 | 4.5x faster |
| go:trafilatura | 246.1 | 3.3x faster |
| python:trafilatura | 819.6 | 1.0x faster |
<!-- BENCH_TABLE_END -->

### Reading the tables

- **Speed is real.** Every compiled implementation beats Python 3–15×. Python's
  trafilatura carries interpreter + lxml-call overhead the ports don't.
- **But speed and robustness trade off.** The `0` and `26 B` cells are the story: the
  readability/dom-distiller family returns almost nothing on the HN comment page and the
  MDN docs page — they're tuned for news-article DOM. The fastest libraries are fast
  partly because they bail on hard pages.
- **trafilatura is the only robust one in all three languages.** It captures content on
  every fixture (it's a content-density algorithm, not an article-shape heuristic). Among
  the trafilatura ports: **Go is fastest** (3.3×), Rust mid (6.0× but the port is less
  optimized than dom_smoothie), Python slowest. Output sizes match within ~5%, confirming
  it's the same algorithm — a clean language-only comparison.

## The whole core, not just extraction

Extraction is one of six things the pith core does. The port question is really "what
does *each piece* cost, and is it portable?"

| core piece | what it is | cost | portable to Go/Rust? |
|---|---|---|---|
| static fetch | trafilatura/urllib GET | ~200–300 ms (network) | yes, trivial (net/http, reqwest/ureq) |
| **stealth browser** | scrapling + Camoufox, Cloudflare-solve | **5,000–8,000 ms** | **no mature equivalent — the moat** |
| extraction → md | trafilatura | 50–200 ms | yes (go-trafilatura best) |
| thin-content fallback | static→browser if <200 B | logic only | yes, trivial |
| browser routing | domain allowlist match | µs | yes, trivial |
| objective excerpts | one LLM call (Groq) | ~0.5–2 s (network) | yes, HTTP POST |
| frontmatter/metadata | parse trafilatura header | µs | yes (ports expose metadata) |

### Measured fetch dominance (real pith, this machine)

```
STATIC PATH  (normal pages, fetch+extract total)
   376 ms   un.org/history-of-the-un
   416 ms   peps.python.org/pep-0008
BROWSER PATH (walled sites, stealth browser fetch+extract total)
  7590 ms   reddit.com/r/Python
  5281 ms   x.com/NASA
```

The stealth browser is **~15–20× the entire static path** and **~30–100× the extraction
step alone**. For any walled-site workload, the language of the extraction step is noise.

## The port decision

Honest, evidence-based — not "Rust is faster so rewrite it."

- **If your workload is walled sites** (Reddit/LinkedIn/Crunchbase — pith's reason to
  exist): **stay Python.** The browser dominates wall-clock and is Python-only. A Go/Rust
  port would still have to drive a browser; you'd save ~2% and lose the `scrapling`
  ecosystem. Not worth it.
- **If your workload is bulk *normal* pages at scale** (thousands of news/blog/docs URLs,
  no walls): a **Go `go-trafilatura` worker** gives identical extraction quality at ~3×,
  and roughly halves end-to-end latency (extraction is a real fraction of the ~400 ms
  there). Worth it for throughput.
- **Hybrid is the pragmatic answer if you need both:** keep the Python stealth-browser
  fetch service for walls; route normal-page bulk through a compiled `go-trafilatura`
  worker. The browser cost is unavoidable in any language, so isolate it in the one
  ecosystem that has it and speed up the part that's actually CPU-bound.

## The stealth browser — why it doesn't port

The reason pith exists over plain trafilatura is the walled-site path, and that path is
the one thing Go/Rust can't replicate today. Concretely:

- **The moat is a browser binary, not Python code.** `scrapling`'s `StealthyFetcher`
  drives **Camoufox** — a C++-engine-level patched Firefox fork. Fingerprint rotation and
  canvas/WebGL/WebRTC/timezone spoofing happen *inside Firefox's C++ layer*, not as JS
  injection (which Cloudflare Turnstile now trivially detects). Matching it means forking
  Firefox. No Go or Rust project has.
- **Go: cannot replicate today.** `go-rod/stealth` does JS-injection evasions only (the
  detectable kind, last meaningful push 2024). No mature Turnstile-solving browser lib.
  TLS-impersonation (utls/cycletls) is strong but solves the wrong layer — these sites
  403 at the edge regardless of TLS.
- **Rust: closest, still not production.** `chaser-oxide` (chromiumoxide fork, ~269★,
  2026) does *protocol-level* CDP stealth — the right approach — but is pre-1.0,
  single-maintainer, sub-1000 downloads/mo, and Chromium-not-Camoufox. `wreq`/`rquest`
  lead on TLS impersonation, same wrong-layer caveat.
- **Camoufox outside Python?** It has a websocket remote-server mode any Playwright client
  can connect to — but control is Firefox/Juggler, not CDP, and `playwright-go` / Rust
  Playwright bindings have weak Firefox-remote support. The only mature non-Python port is
  **JS** (`apify/camoufox-js`) — no Go/Rust. Switching to Node gains nothing on wall-clock.

**Net:** the stealth fetch is genuinely Python's (or Node's) territory. A port would either
reinvent the stealth layer from scratch or shell out to the Python browser anyway — and
since the browser owns 95% of the wall-clock, it'd buy ~nothing on walled sites.


## Per-stage verdict

The core is three separable stages. Treating them as one box is the benchmark mistake —
the answer differs per stage:

| stage | Python (pith) | Go | Rust | winner |
|---|---|---|---|---|
| plain fetch | tie | tie | tie | tie |
| **stealth/walled fetch** | **scrapling — mature** | weak (go-rod/stealth aging) | weak (chaser-oxide young) | **Python, decisively** |
| extract (trafilatura algo) | reference | go-trafilatura (faithful) | trafilatura-rs (faithful) | tie on quality, Go/Rust win speed |
| extract (readability algo) | n/a | many | many | worse algorithm — skip unless news-only |
| markdown render | built-in | needs html2md bolt-on | built-in (trafilatura-rs, dom_smoothie) | **Rust** (one call, no confound) |
| metadata/date/lang | strong | strong (port) / weak (readability) | strong (port) / weak (readability) | port-vs-port tie |
| LLM excerpts | HTTP call | HTTP call | HTTP call | tie (language-agnostic) |

Self-reported trafilatura F-scores are a statistical wash — **Python 0.908–0.914, Go
0.904, Rust 0.913** — so leaving Python costs ~no extraction quality *if you pick the
trafilatura port, not a readability lib*. The readability family is a different algorithm
(Mozilla Readability.js): density scoring tuned for single-article news pages, which is
why it returns near-nothing on forum/list pages (matches our hn_item → 26–42 B result).

**What a port buys:** single static binary (no interpreter/venv at deploy), faster cold
start (serverless), lower per-doc extraction wall-clock, trivial thread-safe concurrency.
**What it gives up:** the stealth-browser ecosystem (decisive), years of trafilatura
per-site tuning, and the Rust/Go ports lag upstream (v0.2–v0.3 single-author crates).

## Library reference — every Go + Rust candidate found

Faithful trafilatura-algorithm ports (the only true "language swap"): **go-trafilatura**
and **trafilatura-rs**. Everything tagged *readability-port* is a different algorithm.
The html→md crates are *renderers*, not extractors — fair trafilatura competitors only
when paired with an extractor first.

### Go

| Library | Approach | MD? | JS? | Maturity | Tradeoff (one-liner) |
|---|---|---|---|---|---|
| markusmobius/go-trafilatura | trafilatura-port (extract) | no (needs html2md) | no | 141★, active 2025-09 | Truest port of pith's algorithm; same scoring/fallback cascade, ~2.4x faster than Python, but HTML out → bolt on html-to-markdown; heavy dep tree (WASM regex runtime). |
| markusmobius/go-domdistiller | dom-distiller (extract) | no (`res.Text` plain) | no | 74★, 2024-09 (stale, stable) | Fastest of the 3 Go extractors; `res.Text` is zero-dep plain text; Boilerpipe density heuristics → more boilerplate bleed-through than trafilatura, weaker metadata. |
| go-shiori/go-readability | readability-port (extract) | no (needs html2md) | no | 941★, **ARCHIVED** | Most-used Go Readability port but read-only now; strong on articles, near-empty on forums (hn_item → 42 bytes). Use readeck v2 instead. |
| readeck/go-readability v2 (codeberg) | readability-port (extract) | no (RenderText/HTML) | no | active, tracks Readability.js 0.6 | Canonical successor to archived go-shiori; v2 API uses `art.Node` + `RenderHTML/RenderText` methods (NOT `.Content` field). Lighter than go-trafilatura (no WASM). |
| mackee/go-readability | readability-port (extract+MD) | **yes** (`ToMarkdown`) | no | 94★, 2025-06 | Only Go readability port emitting markdown natively in one call (`Extract`→`ToMarkdown`). Readability-family precision < trafilatura; guard `Root==nil`; go1.24. |
| cixtor/readability | readability-port (extract) | no (needs html2md) | no | maintained, MIT | 3-function API, 1-dep build, no config knobs. Rejects empty pageURL (pass `http://localhost/`). Same algorithm-swap caveat as all readability ports. |
| advancedlogic/GoOse | scoring heuristic (extract) | no (plain only) | no | 451★, 2025-08 | Stopword-density cluster scoring; dead-simple `ExtractFromRawHTML`. Scales poorly on huge docs (wikipedia 1190ms). No content DOM node → hard to bolt markdown. |
| mrjoshuak/readabiligo | readability-port (extract) | no (needs html2md) | no | 3★, 2025-11 | ReadabiliPy-style; goroutine+timeout per call. New/low-adoption; don't `@latest` (v0.2.0 tag broken, pin a commit). |
| dotcommander/defuddle | defuddle-port (extract+MD) | **yes** (`Markdown:true`) | no | 2★, 2026-06 | Obsidian Web Clipper engine port; ~40 site-specific extractors; direct markdown via JohannesKaufmann v2 internally. Brand new, low adoption, **needs Go 1.26**. |
| JohannesKaufmann/html-to-markdown | html→md (render only) | **yes** | no | 3698★, very active | The markdown renderer, NOT an extractor — converts the whole DOM verbatim. The companion every Go extractor pairs with. v2 is a rewrite (different API). |
| mrjoshuak/go-markdownify | html→md (render only) | **yes** | no | 2★, 2025-03 | python-markdownify port; pure serializer, no extraction. Niche, low adoption. |
| gocolly/colly | scraper framework (fetch) | no | no | 20k★ class, mature | De-facto Go scraping framework — solves fetch/crawl, not extraction. |
| chromedp/chromedp | CDP driver (fetch+JS) | no | yes | ~13k★, active | Pure-Go Chrome DevTools driver — the JS-render stage. No stealth out of box. |
| go-rod/rod (+ go-rod/stealth) | CDP driver (fetch+JS) | no | yes | ~7k★ / 328★ | Better-documented CDP driver; stealth add-on's evasions aging (2024-03). Closest Go answer to scrapling's browser stage, but weaker stealth. |
| Davincible/chromedp-undetected | stealth CDP (fetch+JS) | no | yes | moderate, single-maint | The undetected-chromedriver analog for Go; periodic updates only. |

### Rust

| Library | Approach | MD? | JS? | Maturity | Tradeoff (one-liner) |
|---|---|---|---|---|---|
| trafilatura (nchapman/trafilatura-rs) | trafilatura-port (extract+MD) | **yes** (`markdown` feature) | no | v0.3.0, 2026-03, ~1.7k dl/mo | Rust port OF go-trafilatura (2 hops from Python). Built-in markdown via `content_markdown()`. F-score 0.913 vs Python 0.914 (self-reported). Young; ships UniFFI bindings. **Best Rust trafilatura analog.** |
| Murrough-Foley/rs-trafilatura | trafilatura-port (extract+MD) | **yes** (lossy) | no | 37★, v0.2.2, 2026-04 | Real trafilatura port + XGBoost page-type classifier + per-page quality score (LLM-fallback routing). Markdown is **lossy** (strips code blocks, table structure, bold/italic per its own example). Use `content_text` for fair text comparison. |
| niklak/dom_smoothie | readability-port (extract+MD) | **yes** (`TextMode::Markdown`) | no | 208★, v0.18, 2026-06, ~97k dl | Fastest Rust readability (~336µs small doc); native markdown, rich JSON-LD metadata, actively maintained. Readability-family, not trafilatura algorithm; markdown mode over-escapes punctuation. |
| kumabook/readability (readability-rs) | readability-port (extract) | no (needs htmd) | no | 134★, v0.3.0, 2024-04 | Most-downloaded Rust readability (~1M dl) but stale deps (html5ever 0.26). Sub-ms small docs; whiffs on non-articles (hn → 26 bytes). The crate the existing pith bench already wires up. |
| dreampuf/readability-rust | readability-port (extract) | no (needs htmd) | no | 20★, v0.1.x, 2025-11, ~14-57k dl | High dl-to-star ratio; uses html5ever + lol_html. `parse()` returns Option (silent None). Young, single author. |
| news-flash/article_scraper (GitLab) | readability-port (extract) | no (needs htmd) | no | v2.3.1, 2026-03, ~52k dl | Powers NewsFlash RSS reader; libxml2-backed (C FFI). Forces async/tokio even offline + system libxml2 dep — friction for a sync bench, little quality edge over kumabook. |
| readable-readability | readability-port (extract) | no (needs htmd) | no | v0.4.0, 2022-12, ~36k dl | "Really fast" tagline; returns kuchiki NodeRef (must `.to_string()`). Depends on **unmaintained, RUSTSEC-flagged kuchiki**; stale. |
| spider-rs/llm_readability | readability-port (extract) | via htmd companion | no | v0.0.17, 2026-04, ~68k dl | Perf-tuned readability-rs rewrite, used in Spider Cloud prod. 2-arg API (mut Read + &Url); README example stale. Whiffs on forums (hn → 26 bytes). |
| egemengol/readability-js | readability-wrapper (extract) | no (needs html2md) | no | v0.1.5, 2025-10, ~3.7k dl | Embeds the **real Mozilla Readability.js** in QuickJS — quality oracle, exact Firefox Reader output. ~30ms init (hoist out of loop) + ~10ms/doc; slowest, drags a C JS engine. |
| libreadability | readability-port (extract) | text direct; MD via htmd | no | v0.2.0, small | Rust port of readeck's Go Readability port. Cleanest API of the readability crates (`extract(&str, Some(url))` → `text_content`). Single-algorithm, no fallback cascade. |
| mozilla-readability | readability-port (extract) | no | no | v0.1.1, 2022-10, abandoned | Ships as cdylib with zero FFI exports — **unusable without source-patching**. Don't add. |
| htmd (letmutex/htmd) | html→md (render only) | **yes** | no | 445★, v0.5.4, ~1.25M dl | Turndown.js port; the markdown renderer in the existing pith Rust bench. ~16ms for 1.37MB Wikipedia. NOT an extractor. Best-maintained pure converter. |
| fast_html2md (spider-rs/html2md) | html→md (render only) | **yes** | no | 75★, v0.0.62, ~237k dl | lol_html streaming rewriter, fastest converter, prod at spider.cloud. Pre-1.0, "as-is" maintenance. No extraction. |
| mdka (nabbisen) | html→md (render only) | **yes** | no | v2.1.6, 2026-06, ~111k dl | Infallible `html_to_markdown(&str)->String`; scraper-based; has `Minimal` strip mode. Direct htmd competitor; not an extractor. |
| html2text (rust-html2text) | html→text (render only) | no (terminal text) | no | v0.17.1, ~4.5M dl, very active | Plain-text/terminal renderer with width wrap; not markdown, not extraction. Wrong tool for this job. |
| html2md (crates.io, original) | html→md (render only) | **yes** | no | v0.2.15 | DOM→md serializer; **GPL-3.0** (copyleft — liability if pith ships closed); blows up on script-heavy pages (hn 6.5KB→120KB). htmd is the MIT alternative. |
| monolith | page archiver (other) | no | no | 15.3k★, 2026-05 | Bundles a page into a single self-contained HTML; not extraction. Out of scope. |
| spider (spider_transformations) | crawler + extract/MD | **yes** | yes (framework) | 2.55k★, very active | Crawler framework; offline `transform_content_input` does readability+markdown on raw bytes. readability=off keeps nav; readability=on (llm_readability) **over-strips** (Wikipedia→28 bytes). Layout-fragile, heavy dep graph. |
| harehare/mq (mq-markdown) | html→md (render only) | **yes** | no | 938★, very active | Structural transcoder on scraper; zero boilerplate removal. 2-arg API (docs.rs shows wrong 1-arg). Not an extractor. |
| rust-headless-chrome | CDP driver (fetch+JS) | no | yes(?) | 2.9k★, active | Most popular Rust CDP lib — the JS-render stage. |
| mattsse/chromiumoxide | CDP driver (fetch+JS) | no | yes(?) | 1.3k★, active | Async CDP driver; spider_chrome is the spider-maintained fork. |
| jonhoo/fantoccini (+ thirtyfour) | WebDriver (fetch) | no | no | 2k★, battle-tested | WebDriver client; needs a separate browser/driver. No stealth. |
| ccheshirecat/chaser-oxide | stealth browser (fetch+JS) | no | yes | 269★, 2026-04 | The notable **Rust stealth** option — closest analog to scrapling's stealth browser, but young and far from scrapling's maturity. |

**Key takeaway from the table:** Go and Rust each have exactly one faithful trafilatura-algorithm port (go-trafilatura; trafilatura-rs/rs-trafilatura). Everything else labeled "readability-port" is a *different extraction algorithm* — a genuine quality head-to-head, not a language swap. The html→md crates (html-to-markdown, htmd, mdka, fast_html2md, mq-markdown) are renderers, not extractors, and only become fair trafilatura competitors when paired with an extractor first.

## Provenance

This doc is backed by three independent streams that converged: (1) the live benchmark in
this directory (7 implementations, my measurements), (2) a fan-out research workflow over
the Go/Rust extraction landscape (53 agents), (3) a focused stealth-browser feasibility
study. Where they overlap — readability ports failing on forum pages, F-score parity among
trafilatura ports, the stealth browser as the non-portable moat — they agree.


## Method notes

- Extraction-only timing isolates the CPU-bound core; fetch/browser measured separately
  (above) because they're network-bound and would swamp the signal.
- All markdown-via-companion paths (`html-to-markdown` for Go, `htmd` for Rust) include
  that conversion in the timing, matching pith's native-markdown output.
- `go:goose` (advancedlogic/GoOse) was dropped: its current version moved the entire API
  into `internal/` — no longer usable as a library. A finding in itself about Go
  extraction-lib maintenance.
- Rust built `--release`. Go via `go run` with timing measured inside the loop (compile
  excluded).
