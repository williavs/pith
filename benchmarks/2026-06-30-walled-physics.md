# The physics of walled-site crawling — measured, not assumed (2026-06-30)

Forcing innovation means first measuring the real constraints instead of guessing at
levers. Three hypotheses tested on this machine (16GB, patched Chromium via scrapling 0.4.9).

## H1 — Warm/pooled browser beats cold-launch-per-fetch? **DISPROVEN (0.83×)**

Hypothesis: scrapling cold-launches a stealth Chromium per `fetch()`; reusing a warm `StealthySession`
across pages of one site should collapse per-page cost.

5 pages of one walled domain (reddit subreddits):

| | total | per page |
|---|---|---|
| cold (per-fetch launch, current pith) | 22.2s | 4.4s |
| warm (`StealthySession` reused) | 26.8s | 5.2s (+ 0.6s launch) |

**Warm was slower.** The browser *launch* is only ~0.6s — not the bottleneck. The 4–5s/page
is navigation + Cloudflare-solve + render + network, which a warm browser doesn't avoid.
Worse, a warm session reuses **one fingerprint** across pages (more detectable); cold launches
get a **fresh fingerprint each time** — an anti-detect *benefit*. Pooling is not the lever, and
cold-per-fetch is arguably correct for walls.

## H2 — How far does concurrent-browser crawling scale? **Plateaus at 3 (≈2×)**

6 pages of one walled domain, N concurrent stealth-Chromium instances:

| concurrency | total | pages/sec | ok | bottleneck |
|---|---|---|---|---|
| 1 | 26.1s | 0.23 | 6/6 | — |
| 2 | 15.3s | 0.39 | 6/6 | — |
| **3** | **12.9s** | **0.47** | 6/6 | knee |
| 6 | 12.5s | 0.48 | 6/6 | no gain over 3 |

RAM stayed at 13–14 GB free throughout — **not** memory-bound. The plateau at 3 is
CPU/contention (Chromium render + Cloudflare-solve are CPU-heavy). All pages succeeded at
every level; concurrency didn't degrade success. Validates `_BROWSER_MAX_CONCURRENCY=3`
empirically.

## H3 — The cost asymmetry that should drive the whole design

| tier | per-page | concurrency ceiling | throughput ceiling |
|---|---|---|---|
| open web (cheap: HTTP/impersonation) | ~0.3s | ~8 (CPU/GIL) | **~4 pages/sec** |
| walled (browser) | ~4–5s | ~3 (CPU/contention) | **~0.5 pages/sec** |

**Walled pages are ~10× slower to gather than open pages, and that gap cannot be closed by
throwing concurrency at it** — both tiers are already at their measured knees. 

## What this forces (the strategy follows from the physics)

You **cannot** brute-force-crawl walled gardens. ~0.5 pages/sec means a "crawl all of
LinkedIn" product is physically impossible on commodity hardware. The only winning move is
**relevance-first**: spend the expensive walled fetches *only* on the handful of pages that
carry decision-maker signal, and parallelize the cheap open fetches. The measured cost
asymmetry makes relevance-over-coverage not a preference but a constraint.

## H4 — Does free-threaded Python 3.14 break the parse ceiling? **NO (lxml re-enables the GIL)**

The open-tier "8×" from the enrichment benchmark was **network I/O overlap**, not parse
parallelism. Tested pure parse throughput (trafilatura/lxml, 40 jobs, 12 cores):

| threads | GIL Python 3.12 | free-threaded 3.14 |
|---|---|---|
| 1 | 13.2 jobs/s (1.0×) | 11.9 jobs/s (1.0×) |
| 2 | 14.7 (1.1×) | 11.8 (1.0×) |
| 4 | 12.8 (1.0×) | 10.1 (0.9×) |
| 8 | 10.5 (0.8×) | 8.0 (0.7×) |

Two hard facts:
- **Parse doesn't thread-scale on either build** — it's flat-to-negative. lxml's C parse
  releases the GIL but trafilatura's Python-level scoring re-serializes; adding threads only
  adds contention.
- **Free-threaded 3.14 gives nothing**: importing `lxml.etree` emits *"the GIL has been
  enabled to load module 'lxml.etree', which has not declared that it can run safely without
  the GIL"* — the no-GIL build **turns the GIL back on**. lxml isn't free-threading-safe as of
  2026-06, so the headline Python 3.14 feature does not apply to pith's hot path.

### The measured language verdict (per layer)

| layer | bound by | does language matter? |
|---|---|---|
| stealth browser (the moat) | C++ browser + network + Cloudflare | **No** — the browser does the work; Python/Node drive it fine |
| open/walled fetch concurrency | network I/O | **No** — Python threads overlap I/O fine (the real "8×") |
| **parse at scale** | **CPU + GIL** | **Yes** — Python can't thread-scale parsing; free-threading blocked by lxml. Go/Rust trafilatura ports are thread-safe and 3–15× (measured 2026-06-21) |
| orchestration | — | No |

**Conclusion:** Python is correct for the moat and the orchestration; it is the *weakest* link
only for high-volume parsing, and a compiled `go-trafilatura` worker is the evidence-backed
escape hatch there — not a full rewrite, not free-threading. Switching the driver language buys
nothing on the part that actually costs (the browser).
