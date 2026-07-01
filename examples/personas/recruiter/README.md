# Recruiter persona — building a candidate card with pith

Goal: take one GitHub handle for a promising open-source dev and produce a defensible
candidate card — who they are, where else they're active, what they build, how to reach them,
and how confident we are it's one person. Public data only, no LLM.

Candidate chosen: **`sindresorhus`** (Sindre Sorhus), a prolific, very public OSS maintainer —
a good stress test because the handle is reused everywhere and some sites bot-wall.

## pith calls used

```python
from pith.profiles import enumerate_profiles
from pith import Extractor
from pith.gravatar import gravatar_profile
from pith.resolve import resolve_person, Target

# 1. Footprint: which public profiles exist for this handle (technical-persona subset)
enumerate_profiles("sindresorhus", persona="technical", report=True)

# 2. Pull the GitHub profile itself (bio, meta, outbound social links)
Extractor().extract(["https://github.com/sindresorhus"])

# 3. Reverse-email pivot: public Gravatar -> real name, location, owner-verified accounts
gravatar_profile("sindresorhus@gmail.com")

# 4. Identity corroboration: is each found profile really the same person?
t = Target(name="Sindre Sorhus", website="https://sindresorhus.com",
           anchors={"https://github.com/sindresorhus"})
resolve_person("sindresorhus", t, persona="technical")
```

## What each call gave me

- **`enumerate_profiles`** — coverage `{checked:10, found:4, not_found:4, inconclusive:2}`.
  Confirmed GitHub, DEV Community, Medium, GitLab; flagged Reddit + Twitter as WAF-inconclusive
  (correctly refused to call them "found").
- **`Extractor`** — pulled the bio/headline and the outbound social links (X, Instagram) off
  the GitHub HTML. `structured` was empty (GitHub ships no schema.org Person).
- **`gravatar_profile`** — the strongest single call: real name "Sindre Sorhus", location
  "Norway", and owner-verified links to X and Facebook.
- **`resolve_person`** — turned raw existence into an identity verdict: overall confidence 1.0,
  GitHub + DEV both ACCEPT on BACKLINK/FULL-NAME/COMPANY-DOMAIN, and a ranked `best_channels`
  list (DEV Community, GitHub) for outreach.

## What worked

- One handle in, a corroborated multi-profile card out, with provenance for each field.
- Honest coverage: bot-walled sites are surfaced as inconclusive, not silently dropped or
  reported as hits.
- `resolve_person` is the call that makes this recruiter-usable — it answers "is this actually
  the same person" instead of just "does the handle exist somewhere."

See `candidate.md` for the finished card.
