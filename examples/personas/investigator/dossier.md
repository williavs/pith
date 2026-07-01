# Identity Dossier — Beau Lebens

**Subject:** Beau Lebens (public technologist)
**Starting fact:** one email — `beau@dentedreality.com.au`
**Built with:** pith (public-data only, deterministic, no LLM, no auth)
**Date:** 2026-07-01

---

## Summary

| Field | Value | Source |
|---|---|---|
| Name | Beau Lebens | Gravatar public profile |
| Role | Lead of WooCommerce, at Automattic | Gravatar self-attested bio |
| Location | Golden, CO (US) | Gravatar `currentLocation` |
| Primary handle | `beaulebens` (used identically across every network) | Gravatar linked accounts |

**Overall confidence: MODERATE–HIGH that this handle cluster is one person, and that person is Beau Lebens of Automattic.**
Read the caveats — pith's own numeric score (0.67) is lower than the human read, and the reason is a corroboration gap, not a contradiction. See "Precision caveats."

---

## Confirmed accounts (with the corroborating signal for each)

All four below are marked `verified: true` by Gravatar. **Gravatar "verified" means the account owner
proved control of that account to Gravatar** (e.g. by posting a token) — it is the single strongest
public, deterministic identity signal available here, because the subject attached these accounts to
their own email themselves.

| Account | URL | Corroboration |
|---|---|---|
| X (Twitter) | https://x.com/beaulebens | Gravatar `verified:true`. Direct extraction: page title `Beau (@beaulebens) on X`; page cross-links to @Automattic, @Jetpack, @WooCommerce — consistent with the stated employer. |
| LinkedIn | https://www.linkedin.com/in/beaulebens | Gravatar `verified:true`. Direct extraction: page title `Beau Lebens - Woo | LinkedIn` — full name + WooCommerce, both consistent. |
| GitHub | https://github.com/beaulebens | Gravatar `verified:true`. `resolve_person` → **ACCEPT** (conf 0.67, BACKLINK). Page cross-links github.com/automattic and github.com/woocommerce — consistent with employer. |
| Instagram | https://instagram.com/beaulebens | Gravatar `verified:true`. NOT independently fetched/corroborated by pith (see gaps). |

### Additional profiles found by handle-enumeration (existence only — weaker)

`enumerate_profiles('beaulebens', persona='technical', report=True)` — coverage: **3 found / 5 not-found / 2 inconclusive of 10 checked.**

| Site | Existence | URL | Corroboration status |
|---|---|---|---|
| GitHub | high | https://news.ycombinator.com/... (see below) | corroborated (above) |
| HackerNews | high | https://news.ycombinator.com/user?id=beaulebens | Exists. Page title `Profile: beaulebens`, no name, no links → **could NOT corroborate** it is the same Beau. Same-handle only. |
| Medium | high | https://medium.com/@beaulebens | Exists. In a controlled test it backlinks to `twitter.com/beaulebens`, so it IS this person's — but see the x.com/twitter.com note below. |

---

## Precision caveats (READ — this is where a false positive or false negative hides)

1. **pith's ACCEPT for GitHub was partly self-referential.** `resolve_person` fired `BACKLINK` because the
   GitHub page links to its own canonical URL `github.com/beaulebens`, which matched the GitHub URL I passed
   as an anchor. When I re-ran with anchors = {x.com, linkedin} only (no GitHub URL), **nothing accepted.**
   So the 0.67 is not independent corroboration of GitHub — it's the anchor matching itself. Treat the
   *number* with suspicion; the real corroboration for GitHub is the Automattic/WooCommerce cross-links,
   which a human reads but the scorer does not credit.

2. **x.com vs twitter.com is a silent gap.** Gravatar hands back the X link as `x.com/beaulebens`.
   GitHub and Medium backlink to the *same* account as `twitter.com/beaulebens`. pith normalizes URLs by
   host and does **not** alias x.com↔twitter.com, so feeding Gravatar's `x.com` form verbatim as an anchor
   **misses** genuine `twitter.com` backlinks. Proof: anchor `twitter.com/beaulebens` → GitHub **and** Medium
   both ACCEPT; anchor `x.com/beaulebens` → neither. An investigator who trusts the raw score would
   under-count real corroboration.

3. **FULL-NAME never fired on any accepted profile.** The owner-name slot reads og:title. On GitHub that is
   `beaulebens - Overview` (handle, not name); on X it is `Beau (@beaulebens) on X` (missing the surname token).
   Only LinkedIn's title (`Beau Lebens - Woo`) contains the full name — and LinkedIn is not in the `technical`
   persona's checklist, so it was never scored. **pith did not independently verify the name "Beau Lebens"
   against any profile it fetched.** The name rests on Gravatar's self-attested profile alone.

4. **LinkedIn extraction pulled unrelated people into `socials`** (e.g. `katiekeithbarn2`, `ian-daniel-stewart`
   — LinkedIn's "people also viewed" sidebar). None matched an anchor here, so no harm, but if any had, it
   would be a **false-positive vector.** Do not trust LinkedIn `socials` as the subject's own links.

---

## NOT verified / bot-walled / inconclusive

| Item | Status | Why |
|---|---|---|
| Reddit `beaulebens` | INCONCLUSIVE | Bot-walled — pith could not read existence either way. |
| Twitter `beaulebens` (via enumerate) | INCONCLUSIVE | Bot-walled at enumeration; the X account is confirmed separately via Gravatar. |
| Instagram | UNCORROBORATED | Gravatar says verified, but pith never fetched/scored the page. Trust = Gravatar only. |
| HackerNews `beaulebens` | SAME-HANDLE ONLY | Profile exists but carries no name/links; cannot tie to this Beau beyond handle reuse. |
| Personal domain `dentedreality.com.au` | NOT corroborated on-profile | `COMPANY-DOMAIN` never fired; the domain does not appear in any fetched profile's links. Email valid (non-role, non-freemail, non-disposable) but the domain→person tie is unproven by pith. |
| Full legal name / employment | SELF-ATTESTED | "Lead of WooCommerce at Automattic" comes from the Gravatar bio the subject wrote; consistent with X/GitHub/LinkedIn cross-links but not independently confirmed by a second authority. |

---

## Provenance (every claim's source)

- `verify_email("beau@dentedreality.com.au")` → valid_syntax, domain dentedreality.com.au, non-role, non-freemail, non-disposable.
- `gravatar_profile("beau@dentedreality.com.au")` → https://gravatar.com/beau — display_name, location, bio, and the 4 verified accounts.
- `enumerate_profiles("beaulebens", persona="technical", report=True)` → coverage 3/5/2 of 10; found GitHub, HackerNews, Medium.
- `resolve_person("beaulebens", Target(name="Beau Lebens", company="Automattic", website="dentedreality.com.au", anchors={github,x,linkedin}))` → confidence 0.67, best_channel GitHub, 1 ACCEPT (GitHub, BACKLINK — see caveat 1).
- Direct `Extractor().extract([...])` on x.com/linkedin/HN → titles and socials cited above.
