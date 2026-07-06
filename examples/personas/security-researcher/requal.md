# pith re-QA — security researcher

Authorized, public-only recon. No exploitation. Defensive review of `_guard_url`
(SSRF) and `contact_evidence` crawl coverage after the rebuild.

- Repo: `/home/willy/projects/pith`
- Python: `/home/willy/projects/pith/.venv/bin/python`
- Date: 2026-07-01

---

## 1. SSRF guard — direct vectors (STILL HOLD)

`_guard_url` (`pith/core.py:73`) rejects non-http(s) schemes and any host that
resolves to a private / loopback / link-local / reserved / multicast address.

Test (`_guard_url` on each input):

| input | result |
|---|---|
| `file:///etc/passwd` | BLOCKED — scheme not allowed: file |
| `http://127.0.0.1/` | BLOCKED — non-public (127.0.0.1) |
| `http://169.254.169.254/` | BLOCKED — non-public (169.254.169.254) |
| `gopher://x/` | BLOCKED — scheme not allowed |
| `ftp://x/` | BLOCKED — scheme not allowed |
| `http://[::1]/` | BLOCKED — non-public (::1) |
| `http://0.0.0.0/` | BLOCKED — non-public (0.0.0.0) |

All three required vectors (`file://`, `127.0.0.1`, `169.254.169.254`) raise
`UnsafeURL`. Direct-vector guard is intact.

---

## 2. TOCTOU / redirect SSRF gap — STILL OPEN

The guard is applied **once to the input URL string**, then the *same string* is
handed to a fetch library that independently re-resolves DNS and follows 3xx
redirects with no per-hop check. Code paths in `pith/core.py`:

- `_fetch_static` (`core.py:105`): `_guard_url(url)` then `trafilatura.fetch_url(url, ...)`;
  fallback `urllib.request.urlopen(req)`. trafilatura and urllib both follow
  redirects by default.
- `_fetch_impersonate` (`core.py:115`): `_guard_url(url)` then `curl_cffi ... creq.get(url)` — follows redirects.
- `_fetch_document` (`core.py:142`): `_guard_url(url)` then `MarkItDown().convert(url)` — refetches the URL itself.
- `_fetch_js` (`core.py:153`): `_guard_url(url)` then `StealthyFetcher.fetch(url)` — a real browser, follows redirects.

Confirmation there is **no per-hop / connection-time guard anywhere**:

```
grep -n "HTTPRedirectHandler|redirect_request|allow_redirects|max_redirects|build_opener|redirect" \
     pith/core.py pith/cli.py
# 0 matches
```

Consequences (analysis only — NOT exploited):

- **Redirect bypass:** a public host that answers `302 -> http://127.0.0.1/`
  (or `http://169.254.169.254/`) passes the guard on the public input URL, then
  the fetch lib follows the hop to the internal target with no re-check.
- **DNS rebinding (TOCTOU):** `_guard_url` calls `getaddrinfo` once
  (`core.py:83`); the fetch lib resolves again at connect time. A host that
  returns a public A record to the guard and a private one to the fetch bypasses
  the check. The window is the classic time-of-check/time-of-use gap.

Root cause: the guard validates a *string*, but never controls the actual
socket the fetch opens (no pinned-IP connection, no redirect handler that
re-runs `_guard_url` on each `Location`). Status: **still a gap.**

### Bonus (new observation): crawl entry point is fully unguarded

`crawl_site` (`pith/cli.py:586-587`) fetches the seed with a raw
`urllib.request.urlopen(seed, ...)` and **no `_guard_url` at all**.
`contact_evidence` calls `crawl_site(website)` first (`cli.py:246`), so the very
first request of an evidence run skips the guard entirely. The per-URL extract
that follows is guarded, but the seed fetch is not. (Not exercised against any
internal host.)

---

## 3. contact_evidence vs raw Extractor on python.org — STILL UNDER-COVERS

Raw `Extractor` on the published contact page vs `contact_evidence` on the site
root:

- **Raw `Extractor("https://www.python.org/about/help/")` emails:**
  `psf@python.org`, `python-announce@python.org`, `webmaster@python.org`
- **`contact_evidence("https://www.python.org")` emails:** `[]` (empty)
- **Missed by contact_evidence:** all three above.

`coverage.ok == ['https://www.python.org']` — only the homepage was crawled; the
`/about/help/` page carrying the addresses was never visited.

### Root cause (verified) — gzip is not decoded

`crawl_site` (`cli.py:586-587`) does:

```python
html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
```

The python.org homepage responds `Content-Encoding: gzip` (body starts
`\x1f\x8b...`, 11,656 bytes). `urllib` does **not** auto-decompress, so
`.decode("utf-8","ignore")` runs on raw gzip bytes and yields garbage.
Result: the homepage HTML has **0 parseable `href`s**, so `_section_links`
(`cli.py:564`) matches nothing and `crawl_site` returns only the seed. With no
`about/contact/team/...` pages discovered, `contact_evidence` extracts the
homepage alone and finds none of the published addresses.

The raw `Extractor` path succeeds because it fetches through trafilatura, which
handles gzip correctly.

So this is a different mechanism than the prior "crawl missed the contact page"
(one-level depth) theory: here the crawl is blinded at step one because the seed
HTML is never decompressed. Any gzip-serving homepage (very common) crawls as
homepage-only.

---

## Verdict

- (a) **TOCTOU / redirect SSRF gap: STILL OPEN.** `_guard_url` checks the input
  string once; no fetch path re-guards redirects or pins the resolved IP
  (`pith/core.py:105-174`; 0 redirect-handler matches). Plus `crawl_site`'s seed
  fetch is entirely unguarded (`pith/cli.py:586-587`).
- (b) **contact_evidence STILL under-covers.** python.org: raw Extractor finds
  `{psf@, python-announce@, webmaster@}@python.org`; contact_evidence finds
  `{}`. Root cause: crawl_site does not gunzip the seed HTML → 0 links → homepage
  -only crawl.
- (c) **Direct-vector guard STILL HOLDS.** `file://`, `127.0.0.1`,
  `169.254.169.254` (and `::1`, `0.0.0.0`, `gopher`, `ftp`) all raise
  `UnsafeURL`.

Public/defensive only. No exploitation performed.
