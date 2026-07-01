# Journalist persona — verifying a source with pith

**Task:** A tipster emailed claiming to be a public figure (Beau Lebens, Automattic/
WooCommerce) from `beau@dentedreality.com.au`, using the handle `beaulebens`. Before
quoting them I had to (a) prove the handle belongs to that person from public data and
(b) find a citeable public contact channel — with a source URL for every claim, because
my editor will ask.

See `verification.md` for the full claims→evidence table and the trust verdict.

## What I ran (all public, deterministic, no auth)

| Step | pith call | Why |
|------|-----------|-----|
| 1 | `verify_email(email)` | Grade the address itself: personal vs role/freemail/disposable. Bundled lists, no network. |
| 2 | `gravatar_profile(email)` | The email→identity pivot. md5(email) → public Gravatar JSON with display name, bio, and **owner-verified** linked accounts. |
| 3 | `enumerate_profiles(handle, persona="technical", report=True)` | Confirm the handle is a live public profile across the web, with a **coverage** block so I see what could NOT be checked. |
| 4 | `resolve_person(handle, Target(...), persona="technical")` | Corroboration, not just existence: fetch each candidate and score it against known facts (name, company, anchor URLs). Only ACCEPTs surface. |

Run with: `../../.venv/bin/python` (repo venv). Snippets are inline in `verification.md`.

## How good was the provenance?

**Strong where it counts, and honest about its gaps — which is exactly what a journalist
needs.**

- **Every datum has a source URL.** Gravatar profile, each linked account, each enumerated
  profile, the fetched GitHub page — all citeable public URLs. Nothing came back as an
  unsourced assertion. `enumerate_profiles(report=True)` even hands you the exact profile
  URL per hit, so the claims table writes itself.
- **It refuses to guess.** Bot-walled sites (Reddit, Twitter) came back `inconclusive`, not
  "no account." That's the difference between "I couldn't check" and "it isn't there" — the
  distinction that stops a false negative from becoming a false claim.
- **Existence vs identity is enforced in the API, not left to me.** `enumerate_profiles`
  reports existence; `resolve_person` reports corroborated identity and surfaces only
  ACCEPTs. The docstrings hammer "a live handle is not proof of identity." Good guardrail.

### Where the provenance is thinner than the numbers suggest

- **`resolve_person` confidence can be misleading.** GitHub scored 0.67 on a single
  `BACKLINK` signal that turned out to be the page's own canonical URL matching my anchor
  set — a self-reference, not independent corroboration. The genuinely independent body
  link (`twitter.com/beaulebens`) didn't score because pith treats `x.com` and
  `twitter.com` as different hosts. Lesson: read the `signals`/`links`, don't trust the
  scalar `confidence` alone.
- **The whole chain rests on one source: Gravatar.** If someone poisoned or spoofed a
  Gravatar, the rest follows. For a real story I'd want a second independent anchor.
- **pith verifies the handle, never the emailer.** Nothing here proves the person who
  contacted me controls the accounts. That last mile is an out-of-band nonce challenge,
  which is outside the tool by design — but it's the step that actually protects the byline.

## Bottom line for the persona

pith turned "someone claims to be X" into a sourced, reproducible evidence table in four
calls. It got me confidently to *the handle is really Beau's*, kept verified and unverified
strictly separated, and never invented a citation. It did **not** — and cannot — get me to
*the emailer is really Beau*; treating its 0.67 as if it did would be the thing that
embarrasses me. Used as an evidence-gatherer feeding a human judgment call, it's a strong
fit for source verification.
