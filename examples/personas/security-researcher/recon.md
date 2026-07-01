# Public Footprint Recon — python.org (Python Software Foundation)

Authorized, defensive open-source recon. PUBLIC pages only. No exploitation, no auth
bypass, no non-public access. Every value below is what `pith` actually returned.

Target: `https://www.python.org/` — a major public open-source org, lawful to footprint
from public pages.
Tool: `pith` (deterministic public-data extraction SDK, no LLM).
Date of run: 2026-07-01.

---

## 1. Tech / surface fingerprint — `website_intel("https://www.python.org/")`

| field            | value           |
|------------------|-----------------|
| builder          | unknown         |
| hosted_builder   | false           |
| framework        | null            |
| responsive       | true            |
| https            | true            |
| copyright_year   | 2001            |
| dated_signals    | `old-jquery`    |
| modernness_grade | B (78/100)      |
| domain           | python.org      |
| domain_age_years | 31              |

Defensive read: HTTPS enforced, long-lived domain (31 yrs → not a lookalike/typo-squat).
The one surface signal that matters here is `old-jquery` — a legacy jQuery version is a
recurring source of DOM-XSS / prototype-pollution CVEs and is worth confirming the exact
version against known advisories. Note the fingerprinter returned `builder=unknown` /
`framework=null` for a site that is in fact a custom Django app — recall is low on
non-templated custom sites (see friction notes in README).

## 2. Exposed public contacts — `Extractor` on public pages

Pages fetched (all public, linked from site nav): `/about/`, `/psf/`, `/community/`,
`/about/help/`.

Publicly published email addresses (from `/about/help/`):
- `psf@python.org`
- `python-announce@python.org`
- `webmaster@python.org`

No phone numbers, no schema.org Person/Organization entities, no postal addresses were
exposed on the crawled public pages. `errors: []` (clean batch).

Defensive read: these are role addresses (psf@, webmaster@, announce@), not individual
inboxes — good hygiene, lower phishing-pivot value than named personal addresses would be.
The published addresses define the org's inbound phishing/impersonation surface.

## 3. Public social presence — `Extractor` socials + `enumerate_profiles`

Authoritative org handles (linked directly from python.org, so identity-confirmed):
- GitHub:   `https://github.com/python`
- X/Twitter: `https://twitter.com/ThePSF`
- LinkedIn:  `https://www.linkedin.com/company/python-software-foundation`

`enumerate_profiles` username sweep (462 sites checked per handle, with coverage report):

Handle `python` — coverage: checked 462, found 240, not_found 184, inconclusive 38.
High-value confirmed-shape hits: GitHub, HackerNews, Medium, Substack.

Handle `ThePSF` — coverage: checked 462, found 52, not_found 368, inconclusive 42.
High/med hits: GitHub, Medium, GitLab, Bluesky, TikTok, YouTube, WordPress.

Defensive read: `python` is a dictionary word, so most of the 240 "found" hits are
unrelated squatters, NOT the PSF — existence-only, no identity correlation (the tool's
own docstring says to resolve each hit before trusting it). `ThePSF` is the discriminating
handle: 52 hits is a realistic org fanout and each high/med hit is a real
brand-impersonation monitoring candidate (someone registering `ThePSF` on a platform the
PSF does not control). The `inconclusive` list (Twitter, Reddit, HackerOne, etc.) is
sites pith could NOT check — a defender should treat those as unknown, not clear.

---

## pith SSRF/LFI guard — verified BLOCKING

`_guard_url` was exercised directly to confirm pith is safe to run as a service (it fetches
user-supplied URLs). All of the following raised `UnsafeURL` and were refused BEFORE any
network fetch:

| target                         | result  | reason                                  |
|--------------------------------|---------|-----------------------------------------|
| `file:///etc/passwd`           | BLOCKED | scheme not allowed (LFI)                |
| `http://127.0.0.1/`            | BLOCKED | loopback                                |
| `http://169.254.169.254/`      | BLOCKED | link-local (cloud metadata)             |
| `http://localhost/`            | BLOCKED | resolves to ::1                         |
| `http://[::1]/`                | BLOCKED | IPv6 loopback                           |
| `http://10.0.0.1/`             | BLOCKED | RFC1918 private                         |
| `http://192.168.1.1/`          | BLOCKED | RFC1918 private                         |
| `gopher://evil/`, `ftp://…`    | BLOCKED | scheme not allowed                      |
| `http://2130706433/` (decimal) | BLOCKED | resolves to 127.0.0.1                    |
| `http://0177.0.0.1/` (octal)   | BLOCKED | resolves to 127.0.0.1                    |
| `http://0x7f.0.0.1/` (hex)     | BLOCKED | resolves to 127.0.0.1                    |
| `http://127.1/` (short)        | BLOCKED | resolves to 127.0.0.1                    |
| `https://www.python.org/`      | ALLOWED | public — control, correctly passes      |

Encoded-IP bypasses (decimal/octal/hex/short-form) all fail because the guard checks the
**resolved** address via `getaddrinfo`, not the URL string — the correct design. Non-http(s)
schemes are refused outright, closing the `file://` LFI and `gopher://`/`ftp://` pivots.

Verdict: SSRF/LFI guard verified blocking file://, 127.0.0.1, 169.254.169.254, and every
private/encoded variant tested. Safe to expose as a fetch service against these vectors.

Residual gaps NOT tested against a live host (documented, not exploited):
- TOCTOU / DNS-rebinding: `_guard_url` resolves the host once, then trafilatura / urllib /
  curl_cffi / scrapling each re-resolve independently at fetch time. A hostile low-TTL
  record could pass the guard, then rebind to an internal IP for the actual fetch.
- Redirect following: the guard runs on the input URL only; `urllib`/trafilatura follow
  3xx redirects without re-guarding the redirect target, so a public URL that 302s to
  `http://127.0.0.1/` is not re-checked in the code path (`_fetch_static`, core.py:104).
These are design observations from reading the fetch path — a defender running pith as a
service should pin resolution or re-guard post-redirect. See README for detail.
