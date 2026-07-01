# Persona: Security Researcher (defensive / authorized)

Stress-testing `pith` by doing the actual job: authorized, public-footprint mapping of an
organization's PUBLIC web presence — the open-source recon phase of a defensive security
assessment. Public pages only. No exploitation, no auth bypass, no non-public access.
Everything in `recon.md` is what pith actually returned.

Target chosen: `https://www.python.org/` (Python Software Foundation) — a major public
open-source org, lawful to footprint from its public pages.

## What I did, and which pith calls

1. **Surface fingerprint** — `website_intel("https://www.python.org/")`
   One call → builder, framework, HTTPS, domain age, and `dated_signals`. Used to seed the
   attack-surface prior (it flagged `old-jquery`).

2. **Exposed public data** — `Extractor().extract([...public pages...], concurrency=4)`
   Pulled emails / phones / socials / schema.org entities off `/about/`, `/psf/`,
   `/community/`, `/about/help/`. These are free on every `Result` — no LLM. Found the org's
   published role addresses on `/about/help/`.

3. **Published contacts** — `find_contact("https://www.python.org/")`
   The convenience wrapper. (Underperformed the primitive here — see friction below.)

4. **Public social presence** — `enumerate_profiles("python", report=True)` and
   `enumerate_profiles("ThePSF", report=True)`
   Username sweep across 462 sites with a coverage report (found / not_found / inconclusive).
   Used to enumerate brand-impersonation monitoring candidates.

5. **Tool safety validation** — `_guard_url` on `file:///etc/passwd`, `http://127.0.0.1/`,
   `http://169.254.169.254/`, plus loopback/private/encoded-IP variants. Confirmed each
   raises `UnsafeURL` before any fetch. This is the researcher validating pith is safe to
   run as a service, not an attack.

## Defensive framing

This is footprint mapping a defender does on their OWN (or an authorized client's) public
presence to answer: what does the internet already expose about us, and where is our
impersonation / phishing surface? All targets here are public pages of a public org. The
SSRF/LFI section validates that pith itself will not become an SSRF pivot if run as a
service — a control test, run against the tool, not the target.

## Reproduce

```bash
cd /home/willy/projects/pith
.venv/bin/python - <<'PY'
from pith.cli import website_intel, find_contact
from pith import Extractor
from pith.profiles import enumerate_profiles
from pith.core import _guard_url, UnsafeURL

print(website_intel("https://www.python.org/"))
print(Extractor().extract(["https://www.python.org/about/help/"], concurrency=1).results[0].emails)
print(enumerate_profiles("ThePSF", report=True)["coverage"])
for u in ("file:///etc/passwd", "http://127.0.0.1/", "http://169.254.169.254/"):
    try: _guard_url(u); print("ALLOWED", u)
    except UnsafeURL as e: print("BLOCKED", u, "-", e)
PY
```

## DX assessment (honest, from doing the job)

### What pith made easy
- **One-call fingerprint.** `website_intel` gives HTTPS, domain age, and dated-library
  signals deterministically — good attack-surface priors with zero setup.
- **Structured extraction is free and robust.** Every `Result` carries emails/phones/
  socials/schema.org; input order is preserved and one failed URL lands in `.errors`
  instead of sinking the batch (`errors: []` on my run).
- **Honest coverage reporting.** `enumerate_profiles(report=True)` surfaces `inconclusive`
  sites (WAF/timeout) instead of silently reading a gap as "no account." That distinction
  is exactly what a defender needs — it kept me from treating unchecked sites as clear.
- **The SSRF/LFI guard is well-built.** It checks the *resolved* IP, so decimal/octal/hex/
  short-form encodings of 127.0.0.1 all fail, and non-http(s) schemes are refused outright.

### Missing recon primitives (concrete)
The core external-footprint primitives are absent — pith is a page fetcher, not a recon
suite:
- **Subdomain enumeration** — the #1 footprint primitive. No way to discover
  `docs./bugs./mail.python.org` from the apex. Biggest single gap.
- **DNS records** — no A/AAAA/MX/NS/TXT, so no SPF/DKIM/DMARC posture and no mail-infra map.
- **Certificate transparency** (crt.sh) — the standard subdomain + internal-hostname
  discovery source. Absent.
- **HTTP security headers** — `website_intel` returns `https: true` as a bool but never
  reports CSP / HSTS / X-Frame-Options / X-Content-Type-Options. Header posture is core to
  a defensive review.
- **robots.txt / sitemap as recon** — `read_sitemap` exists internally but isn't surfaced
  as intel (disallowed paths are a classic tell).

### Friction / bugs hit
- **`find_contact` underperformed the raw primitive.** For python.org it crawled only 1
  page (`pages: 1`) and returned **zero emails**, while a direct `Extractor` call on
  `/about/help/` found `psf@`, `webmaster@`, and `python-announce@python.org`. The
  convenience wrapper's homepage-nav crawl (`crawl_site`, one level into `_SECTIONS`) missed
  the page carrying the org's published contacts. A researcher who trusts `find_contact`
  gets a false "no contacts" for a site that clearly publishes them.
- **`enumerate_profiles` false-positive risk on dictionary handles.** `python` returned 240
  "found" with no identity correlation — most are unrelated squatters, not the PSF. Usable
  only after manual per-hit verification (which the docstring admits). Fine for a
  discriminating handle like `ThePSF`; noisy-to-useless for a common-word handle.
- **Low fingerprint recall on custom sites.** `builder=unknown` / `framework=null` for
  python.org, which is a custom Django app. The grader still returned B/78, but the specific
  stack — the part a defender wants — was blank.

### Ways the tool itself could be abused (dual-use)
- **Username-harvest / doxxing engine.** `enumerate_profiles` fans a single handle across
  462 platforms at `workers=25`. That is a ready-made cross-platform account-harvest
  primitive against an individual. The SSRF guard protects internal targets but nothing
  rate-limits or throttles the outbound sweep against third-party sites.
- **Residual SSRF via TOCTOU / redirects (design observation, not exploited).**
  `_guard_url` resolves once, then trafilatura/urllib/curl_cffi/scrapling re-resolve and
  follow redirects independently (`_fetch_static`, core.py:104). A hostile low-TTL host
  could rebind post-check, or a public URL could 302 to `http://127.0.0.1/` without the
  redirect target being re-guarded. Mitigation: pin the resolved IP for the actual fetch,
  or re-guard every redirect hop. I did not attempt to exploit this — it's from reading the
  fetch path.
