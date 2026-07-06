# Recruiter Re-QA — `pith` after rebuild

*Persona: technical recruiter sourcing an OSS dev. Candidate: **Sindre Sorhus** (`sindresorhus`).
Public data only. Every field traces to a specific pith call. Re-run date: 2026-07-01.*

Python: `/home/willy/projects/pith/.venv/bin/python`

---

## Candidate card

- **Name:** Sindre Sorhus — from public **Gravatar** (`gravatar_profile("sindresorhus@gmail.com")`
  → `exists=True`, `display_name="Sindre Sorhus"`, `location="Norway"`).
- **Location:** Norway (Gravatar).
- **Primary handle:** `sindresorhus`, consistent across every confirmed profile.
- **Headline (GitHub `<title>`):** "sindresorhus - Overview".

### Confirmed profiles — `enumerate_profiles("sindresorhus", persona="technical", report=True)`

| Site | URL | kind | value | gets |
|---|---|---|---|---|
| DEV Community | https://dev.to/sindresorhus | firmographic | high | engineering writing + technical identity |
| GitHub | https://www.github.com/sindresorhus | firmographic | high | technical role, employer in bio, projects, activity |
| Medium | https://medium.com/@sindresorhus | psychographic | high | thought-leadership topics |
| GitLab | https://gitlab.com/sindresorhus | firmographic | med | dev projects, employer |

**Coverage:** `{checked: 10, found: 4, not_found: 4, inconclusive: 2, inconclusive_sites: ['Reddit', 'Twitter']}`
— bot-walled sites (Reddit, Twitter) are surfaced as inconclusive, not dropped or faked. This part works.

---

## Prior bug re-test — VERDICTS

Both bugs re-tested against `Extractor().extract(["https://github.com/sindresorhus"])`, `.results[0]`.

### Bug 1 — GitHub site chrome leaks into `r.socials`  →  **STILL BROKEN (worse)**

`r.socials` returned **17 URLs; only 3 are real profiles.** The other 14 are GitHub site
chrome / marketing / nav — exactly the class of bug reported before, now with a wider leak
(`api.github.com`, `collector.github.com`, `docs.github.com` subdomains, plus a dozen
`github.com/<marketing-slug>` pages).

Actual `r.socials`:

```
https://api.github.com/cmc            <- chrome
https://collector.github.com/github   <- telemetry endpoint (prior bug, still here)
https://docs.github.com/articles      <- chrome
https://docs.github.com/get-started   <- chrome
https://docs.github.com/site-policy   <- chrome (prior bug, still here)
https://github.com/accelerator        <- marketing
https://github.com/customer-stories   <- marketing
https://github.com/fluidicon          <- favicon asset
https://github.com/mcp                 <- product
https://github.com/partners           <- marketing
https://github.com/premium-support    <- marketing
https://github.com/resources          <- marketing
https://github.com/sindresorhus       <- REAL
https://github.com/solutions          <- marketing
https://github.com/why-github         <- marketing (prior bug, still here)
https://instagram.com/sindresorhus    <- REAL
https://twitter.com/sindresorhus      <- REAL
```

Every one of these is also emitted as a `Fact(kind="social")` with `corroboration=1`, so a
downstream consumer reading `r.facts` gets the same 14 false profiles.

**Root cause:** `pith/extract.py` `_is_profile()` only rejects handles in a fixed
`_SOCIAL_HANDLES` denylist. The denylist misses `site-policy`, `why-github`, `accelerator`,
`customer-stories`, `partners`, `premium-support`, `resources`, `solutions`, `mcp`, `fluidicon`,
`cmc`, `get-started`, `articles`, and it does nothing about the `api.` / `collector.` /
`docs.` subdomains that the `(?:[a-z0-9-]+\.)?github\.com` prefix in `_SOCIAL` happily matches.
A denylist can't keep up with GitHub's marketing slugs — this needs an allowlist / owner-link
scope (only links inside the profile's own sidebar), not more denylist entries.

### Bug 2 — fediverse rel=me handle coerced into a fake mailbox  →  **STILL BROKEN**

`r.emails` returned exactly one "email", and it is the fake one:

```
r.emails = ['sindresorhus@mastodon.social']
```

`mastodon.social` is a Mastodon instance, not a mailbox host. `sindresorhus@mastodon.social`
is his fediverse `rel="me"` handle (`@sindresorhus@mastodon.social`), which is email-*shaped*
but is not a real address. It is also emitted as `Fact(kind="email", labels={'role': False,
'freemail': False}, corroboration=1)` — i.e. presented as a clean personal email. A recruiter
emailing it would bounce.

**Root cause:** `emails()` / `_junk_email()` in `pith/extract.py` gate on asset extensions,
placeholder locals, and placeholder domains, but have no notion of known non-mail hosts
(Mastodon/fediverse instances) and don't treat a `@user@host` fediverse token differently
from a `user@host` mailbox.

---

## Verdict summary

| Prior bug | Status |
|---|---|
| 1. GitHub site chrome leaks as "socials" | **STILL BROKEN** — 14 of 17 socials are chrome (was ~3 before; regression is wider) |
| 2. `mastodon.social` handle emitted as email | **STILL BROKEN** — only "email" returned is the fake one |

Neither prior finding is fixed. `enumerate_profiles` + coverage reporting is solid; the
single-page `Extractor` contact fields (`r.socials`, `r.emails`) are not trustworthy for a
GitHub source.

---

## Biggest remaining gap for sourcing

**Skills / activity signal is thin, and the one "email" is a false positive.**

A recruiter needs three things off a candidate: how to reach them, what they build, and how
active they are. Right now:

- **Contact is unreliable.** The only address pith surfaces (`sindresorhus@mastodon.social`)
  is not emailable, and it is labeled as a clean personal email — a worse failure than
  returning nothing, because it looks trustworthy.
- **Socials must be hand-filtered.** 82% of `r.socials` from the GitHub page is noise; a
  recruiter can't consume the field as-is.
- **No skills/activity extraction.** From the GitHub profile pith pulls the `<title>` but not
  the bio text, pinned repos, primary languages, contribution recency, or follower count —
  the fields that tell a recruiter *what this person builds and whether they're active*.
  Employer inference ("Full-Time Open-Sourcerer" / self-employed) is not surfaced either.

Fix priority for sourcing use: (1) stop emitting fediverse handles as emails, (2) scope
GitHub socials to the profile's own outbound links, (3) extract bio + languages + activity
recency so the candidate card has real skill signal instead of just a title string.
