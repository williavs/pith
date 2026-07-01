# Persona: OSINT Investigator

Build an identity dossier from one thin fact — a public email — using pith only. Public data,
deterministic, no LLM. The bar is **precision**: a wrong-person link is a serious error, so every
claim carries a source and an explicit confidence, and everything pith could not verify is stated.

## Subject

Beau Lebens (`beau@dentedreality.com.au`) — a long-public Gravatar of an Automattic/WooCommerce
engineer. Public figure, public data.

## Workflow (the pith calls, in order)

```python
from pith import verify_email
from pith.gravatar import gravatar_profile
from pith.profiles import enumerate_profiles
from pith.resolve import resolve_person, Target
from pith.core import Extractor

verify_email("beau@dentedreality.com.au")          # 1. grade the email itself
g = gravatar_profile("beau@dentedreality.com.au")  # 2. email -> verified linked accounts (the pivot)
handle = "beaulebens"                               # 3. take the shared handle
enumerate_profiles(handle, persona="technical", report=True)   # 4. footprint + coverage
resolve_person(handle, Target(                      # 5. corroborate handle -> the actual person
    name="Beau Lebens", company="Automattic", website="dentedreality.com.au",
    anchors={"https://github.com/beaulebens",
             "https://x.com/beaulebens",
             "https://www.linkedin.com/in/beaulebens"}))
Extractor().extract([...])                          # spot-check individual profiles by hand
```

Result: [dossier.md](./dossier.md).

## Honest note on precision (what an investigator must know)

pith is genuinely useful as a **legal, deterministic email→accounts pivot** — Gravatar's
verified-linked accounts are the strongest single primitive here, and they're provenance-backed by
the subject's own account proof. `enumerate_profiles` honestly separates found / not-found /
**inconclusive (bot-walled)**, which is exactly the humility an investigator needs — it does not
pretend a Cloudflare wall is a "not found."

But the **corroboration layer (`resolve_person`) needs a human in the loop**, for four concrete
reasons found while building this dossier (details in dossier.md):

1. **Self-referential BACKLINK.** Passing a profile's own URL as an anchor makes that profile
   "backlink to itself" → an ACCEPT that isn't independent corroboration. The 0.67 for GitHub
   evaporates when the GitHub anchor is removed.
2. **x.com vs twitter.com is not aliased.** Gravatar returns `x.com/...`; other sites backlink
   `twitter.com/...`. Feeding the raw Gravatar URL as an anchor silently misses real corroboration.
3. **Name is never independently verified.** The owner-name slot reads og:title, which on GitHub/X
   is the handle, not the name. "Beau Lebens" rests on the self-written Gravatar bio alone.
4. **LinkedIn `socials` leaks other people** (the "people also viewed" sidebar) — a false-positive
   vector if any leaked handle matched an anchor.

**Bottom line:** trust `gravatar_profile` verified accounts and `enumerate_profiles` coverage as
provenance-grade. Treat `resolve_person`'s numeric confidence as a lead, not a verdict — read the
signals, not the score, and bridge Gravatar's accounts into `Target.anchors` yourself (resolve does
not ingest them automatically).
