# Re-QA Dossier — Identity Corroboration Rebuild

**Subject:** Beau Lebens (public technologist)
**Starting fact:** one email — `beau@dentedreality.com.au`
**Scope:** public data only, deterministic, no LLM, no auth
**Purpose:** re-test the two identity-corroboration bugs I confirmed before the rebuild
**Date:** 2026-07-01

---

## Verdict up top

| Prior bug | Status | Proof |
|---|---|---|
| 1. Self-canonical URL faked a BACKLINK (a profile "backlinked to itself" when its own URL was handed in as an anchor) → false ACCEPT | **FIXED** | candidate's own URL excluded from the BACKLINK set; signals `[]`, verdict `REJECT` |
| 2. `x.com` ≠ `twitter.com` host mismatch dropped a real cross-link → silent false-negative | **FIXED** | hosts aliased; `x.com` anchor matched `twitter.com` backlink → `BACKLINK` fires |

Both re-tested against the **real** Gravatar for `beau@dentedreality.com.au`. Anchors used are the actual verified accounts Gravatar returned.

---

## Step 1 — Real Gravatar pivot (live)

`gravatar_profile("beau@dentedreality.com.au")` → exists, display name **Beau Lebens**, location Golden, CO. Verified linked accounts (these are the anchors):

| Site | URL | Username | Gravatar-verified |
|---|---|---|---|
| X | `https://x.com/beaulebens` | beaulebens | true |
| LinkedIn | `https://www.linkedin.com/in/beaulebens` | beaulebens | true |
| GitHub | `https://github.com/beaulebens` | beaulebens | true |
| Instagram | `https://instagram.com/beaulebens` | beaulebens | true |

`anchors = {x.com/beaulebens, linkedin.com/in/beaulebens, github.com/beaulebens, instagram.com/beaulebens}`

---

## Step 2 — Bug 1 re-test: no self-accept on own URL

Adversarial construction reproducing the original bug: the candidate's **own** URL is handed in as an anchor (the Gravatar-linked-URL-as-anchor case), and the page self-canonicals (lists its own URL in `sameAs`). Owner name deliberately set to `SomeoneElse` so nothing else can carry it.

```
candidate url : https://github.com/beaulebens
anchors       : ['https://github.com/beaulebens']   # own url handed in
page sameAs   : ['github.com/beaulebens']            # self-canonical
SIGNALS       : []
VERDICT       : REJECT | confidence: 0.0
```

The `score()` BACKLINK line subtracts the candidate's own normalized URL:
`({norm(same)} & {norm(anchors)}) - {cand}` → empty. No self-reference survives. **Fixed.**

---

## Step 3 — Bug 2 re-test: x.com anchor corroborates a twitter.com backlink

The real cross-link shape: Gravatar hands the account as `x.com/beaulebens`; a *different* candidate page (their GitHub) links out to the legacy `twitter.com/beaulebens`. Pre-rebuild this was a host mismatch → no signal → silent false-negative.

```
candidate url    : https://github.com/beaulebens
anchor (gravatar): https://x.com/beaulebens        -> norm: twitter.com/beaulebens
page link        : https://twitter.com/beaulebens  -> norm: twitter.com/beaulebens
SIGNALS          : ['BACKLINK', 'FULL-NAME']
VERDICT          : ACCEPT | confidence: 1.0
```

`_HOST_ALIASES` collapses `x.com → twitter.com` before comparison, so the anchor and the backlink normalize to the same URL and `BACKLINK` fires. **Fixed.**

---

## Step 4 — recipes.accept_identity carries the same two rules as visible knobs

`accept_identity(corroborations, min_signals=2, exclude_self=True, alias_hosts=True)`:

- A candidate whose only signals are self-referential (`source_url == candidate_url`) → **dropped** (returns `[]`). The fake-BACKLINK bug is now a caller-owned `exclude_self` knob.
- An `x.com` self-signal against a `twitter.com` candidate is correctly recognized as self (aliased) and dropped, while the independent `github.com`/`gravatar.com` signals survive → `['BACKLINK','FULL-NAME']`.

Both fixes exist in two places (`resolve.score` and `recipes.accept_identity`) sharing the same `_HOST_ALIASES` table.

---

## Residual risk & friction (honest findings)

1. **BACKLINK is a self-asserted outbound link, yet weighted +2 = decisive.** `score()` fires BACKLINK when the *candidate page* claims `sameAs`/socials pointing at a known-good anchor. That link is authored by whoever controls the candidate page — trivially forgeable. A scam page that lists `sameAs: x.com/beaulebens` plus the target's name earns `BACKLINK(+2)+FULL-NAME(+1)` → confidence 1.0, ACCEPT, from two forgeable page assertions. True corroboration is the **anchor linking back to the candidate** (mutual), which `resolve_person`'s `_xlinks` only captures among enumerated hits, not for an arbitrary candidate. This is the main residual false-positive vector.

2. **Confidence is a scalar you can over-trust.** `round(min(c/3, 1.0), 2)` maps two forgeable signals to a flat `1.0` — indistinguishable from ten independent corroborations. `resolve_person` then sets overall = `max()` confidence across accepts, so a single forged ACCEPT pins the whole identity to 1.0. There is no separation between "one decisive-but-forgeable signal" and "many independent weak signals." Treat 1.0 as "meets threshold," not "certain."

3. **resolve does not auto-ingest Gravatar's verified accounts.** Gravatar returns `verified=True` — Gravatar itself proved the owner controls those accounts, a strictly stronger signal than a self-asserted backlink. But `resolve_person(handle, target)` re-enumerates from the handle and only uses whatever anchors the investigator manually passes; it neither seeds `target.anchors` from the Gravatar accounts nor treats `verified=True` as an accepted profile. The single highest-quality email→account signal available is left on the floor and must be wired in by hand (as `examples/osint/investigate.py` does manually).

4. **Minor friction:** `Target.anchors` must be populated by the caller; there is no one-call `email → resolved identity` path. The pieces (`gravatar_profile` → build `Target` → `resolve_person`/`score`) are correct but un-glued.

---

## Bottom line

Both prior bugs are fixed and verified against live data — the self-reference is excluded and the x.com/twitter.com alias holds, in both `resolve.score` and `recipes.accept_identity`. The remaining exposure is not a regression but a design property: BACKLINK trusts a forgeable outbound link at decisive weight, confidence collapses to a scalar, and Gravatar's `verified=True` accounts are not auto-ingested. Recommend (a) requiring mutual link or Gravatar-verified provenance before granting the +2, and (b) seeding anchors from verified Gravatar accounts.
