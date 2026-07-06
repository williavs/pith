# SDR Re-QA — pith evidence+recipe rebuild

**Date:** 2026-07-01 · **Persona:** SDR building a lead view · **Data:** public only
**API under test:** `contact_evidence(website)` + `recipes.owner_email` / `recipes.rank_phones`
**Live run:** stripe.com, linear.app, vercel.com, posthog.com (`.venv/bin/python`, real crawls)

## Prior bug (RE-TEST)

Before the rebuild, auto-picking a "primary" email for Stripe returned
`accommodations@stripe.com` — an ADA/HR mailbox — because emails were untyped.

### Verdict: FIXED.

Stripe now types every email and `owner_email` skips the functional mailboxes:

```
EMAIL accommodations@stripe.com                 [functional] x1
EMAIL candidatefeedback-applications@stripe.com [functional] x1
EMAIL careers@stripe.com                        [role]       x1
EMAIL jane.diaz@stripe.com                      [person]     x1
EMAIL sales@stripe.com                          [role]       x1
>> owner_email PICK: jane.diaz@stripe.com  [person]
```

`accommodations@` is now labeled `functional` and never selected — the recipe prefers
`(owner, person, role)`, and `functional` isn't in that list. The ADA-mailbox pick is gone.
The mechanism: `_email_type_scoped` buckets on-domain mailboxes that are neither a known role
nor a name-shaped local into `functional`, so a people-preferring recipe passes over them.

Linear behaves sensibly too: no person on the page, so `owner_email` falls back to
`hello@linear.app [role]` — an honest "role" pick, not a garbage one.

## Lead view built (tiny)

| Company | owner_email | type | top phone |
|---|---|---|---|
| Stripe | jane.diaz@stripe.com | person | (888) 926-2289 |
| Linear | hello@linear.app | role | (none) |
| Vercel | None | — | (212) 456-7890 |
| PostHog | security-internal@posthog.com | person (WRONG — see below) | (201) 397-1285 |

## NEW friction found (honest)

**1. `_name_like` false-positive → new bad pick (regression in spirit, not the same bug).**
The "is this a real person" test is `^[a-z]{2,12}[._-][a-z]{2,12}$` — any `word-word`
hyphenated local passes. PostHog's `security-internal@` and `security-reports@` are typed
`person`, so `owner_email` picks `security-internal@posthog.com` — a security intake box, not
a decision-maker. Verified directly:

```
security-internal   name_like=True
security-reports    name_like=True
jane.diaz           name_like=True   (correct)
```

The accommodations@ *class* of bug (functional mailbox chosen) is fixed for single-word
locals, but hyphenated team mailboxes slip back through the `person` gate. An SDR emailing
`security-internal@` as "the owner" is the same category of embarrassing mispick, just rarer.

**2. Phone evidence is noisy and the recipe can't clean it.** `rank_phones` surfaces obvious
junk: Stripe returns `+55555555555`; PostHog returns **36 phones** (fake demo numbers across
random area codes). Corroboration is `x1` for everything, so ranking-by-corroboration can't
separate real from scraped placeholder. As an SDR I'd have to eyeball the list. The recipe is
honest ("here are all of them, you cut") but offers no signal to cut *on* when nothing
corroborates.

**3. Firmographic sizing gap: STILL PRESENT.** Neither `contact_evidence` nor `enrich_company`
returns headcount, revenue, or a size/segment band. `enrich_company` gives socials + typed
emails + careers flag + tech-modernness grade — nothing to size or tier an account. For an SDR
this is the biggest miss: I can reach the account but can't prioritize by company size /
ICP fit without a separate data source.

## Evidence+recipe API vs a one-shot wrapper (SDR ergonomics)

- **More work, but the right amount.** Two calls instead of one (`contact_evidence` then
  `recipes.owner_email`). The upside is real: I can *see* every candidate + its `email_type`
  and know why the pick was made — the old wrapper hid exactly the choice that produced the
  accommodations@ disaster. Trust went up; keystrokes went up slightly.
- **The recipe default `prefer=("owner","person","role")` is a sane SDR default** and is the
  thing that fixes the prior bug. Good that it ships tuned for this persona.
- **Facts-not-strings is a plus:** `best.value` + `best.labels['email_type']` gives me the pick
  and its justification in one object, so a CRM row can store *why*.

## Bottom line

- Prior accommodations@ bug: **FIXED** (Stripe → jane.diaz@stripe.com [person]).
- New friction: `_name_like` mistypes hyphenated team mailboxes as `person` (PostHog
  security-internal@); phone lists are un-filterable noise; **firmographic sizing still absent**.
- API shape: modestly more work than a wrapper, worth it for the transparency that killed the
  original mispick.
