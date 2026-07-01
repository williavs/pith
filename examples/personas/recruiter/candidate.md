# Candidate Card — Sindre Sorhus

*Sourced entirely from public data via `pith`. Every field below traces to a specific pith
call (see README.md). No manual browsing, no private data.*

## Identity

- **Name:** Sindre Sorhus
- **Primary handle:** `sindresorhus` (consistent across every confirmed profile)
- **Location:** Norway
- **Headline (from GitHub bio):** "Full-Time Open-Sourcerer. Focused on Swift & JavaScript.
  Makes macOS apps, CLI tools, npm packages."

Name + location come from the **public Gravatar profile** for his long-public email
(`gravatar_profile` → `exists=True`, display_name "Sindre Sorhus", location "Norway"). The
headline is the `description` meta tag pulled by `Extractor` off the GitHub profile.

## Confirmed profiles

All four below were returned by `enumerate_profiles(persona="technical")` **and** re-scored
ACCEPT by `resolve_person` (identity-corroborated, not just "handle exists"):

| Profile | URL | pith value tag |
|---|---|---|
| GitHub | https://github.com/sindresorhus | high (firmographic) |
| DEV Community | https://dev.to/sindresorhus | high |
| Medium | https://medium.com/@sindresorhus | high |
| GitLab | https://gitlab.com/sindresorhus | med |

Additional accounts, cross-linked from two independent sources:

- **X / Twitter** — https://x.com/sindresorhus — *linked on his Gravatar (owner-verified) AND
  present in the GitHub profile's outbound links.*
- **Facebook** — https://www.facebook.com/sindresorhus — *owner-verified via Gravatar.*
- **Instagram** — https://instagram.com/sindresorhus — *outbound link on GitHub profile.*
- **Personal site** — https://sindresorhus.com — *appears in resolve's corroboration links.*

Bot-walled / could not verify (surfaced honestly by pith, not dropped): **Reddit, Twitter**
returned inconclusive on direct enumeration (WAF challenge), which is why Twitter is confirmed
here via Gravatar/GitHub cross-links instead.

## What they work on (signals)

- **Languages:** Swift and JavaScript (self-stated in bio).
- **Output type:** macOS apps, CLI tools, npm packages — i.e. a prolific package/tooling
  author, not a web-app product engineer.
- **Employer:** "Full-Time Open-Sourcerer" — self-employed on open source. No company employer
  to infer; funding is via sponsorship (see contact).
- **Best outreach channels (pith `best_channels`):** DEV Community, GitHub.

## Public contact channel

- **GitHub** (issues/sponsors on his profile) — the recommended channel per pith's ranking.
- **X** https://x.com/sindresorhus and personal site https://sindresorhus.com — both public.
- No direct personal email was reliably extracted (see caveat below).

## Confidence this is one person

**High.** Two independent corroboration paths agree:

1. `resolve_person("sindresorhus", persona="technical")` returned overall **confidence 1.0**,
   with GitHub and DEV Community both verdict **ACCEPT** on signals `BACKLINK`, `FULL-NAME`,
   `COMPANY-DOMAIN` (the DEV profile links back to github.com + sindresorhus.com and its owner
   name reads "Sindre Sorhus").
2. `gravatar_profile` for his public email independently returns the same name ("Sindre
   Sorhus"), a matching location, and owner-verified links to X and Facebook under that handle.

The single reused handle `sindresorhus`, the matching real name from an owner-controlled
Gravatar, and the mutual back-links between GitHub/DEV/personal-site make handle-collision very
unlikely.

## Caveat (data-quality note)

`Extractor` reported an "email" of `sindresorhus@mastodon.social` for the GitHub page — this is
a mis-parse of a Mastodon `rel=me` link, **not** a real mailbox. Do not use it for outreach.
