# Source Verification — "Beau Lebens" (@beaulebens)

**Scenario:** A person emailed my tip line from `beau@dentedreality.com.au`, claiming to
be Beau Lebens (Automattic / WooCommerce). Before I quote them, I must (a) prove the
public handle `beaulebens` really belongs to that public figure, and (b) find a
citeable public contact channel. Every row below is something `pith` actually returned;
nothing is asserted without a public source URL.

Reproduce: `../../.venv/bin/python` with the snippets in the CLAIM→CALL column.
Run date: 2026-07-01.

## Claims → Evidence

| # | Claim | pith call | Public source (citation) | What pith returned | Verdict |
|---|-------|-----------|--------------------------|--------------------|---------|
| 1 | The email `beau@dentedreality.com.au` is well-formed, personal (not a role/freemail/disposable address) | `verify_email("beau@dentedreality.com.au")` | deterministic syntax + bundled disposable/freemail lists (no network) | `valid_syntax=True, domain=dentedreality.com.au, is_role=False, is_freemail=False, is_disposable=False` | VERIFIED (syntax + classification only — says nothing about who owns it) |
| 2 | That email is tied to a public Gravatar for "Beau Lebens" | `gravatar_profile("beau@dentedreality.com.au")` | https://gravatar.com/beau (JSON: https://gravatar.com/205e460b479e2e5b48aec07710c08d50.json) | `exists=True, display_name="Beau Lebens", location="Golden, CO", about="Lead of WooCommerce, at Automattic. Previously Jetpack, WordPress.com..."` | VERIFIED (public Gravatar API; the md5 of the email resolves to this profile) |
| 3 | The person owns verified-linked accounts on X, LinkedIn, GitHub, Instagram — all `@beaulebens` | `gravatar_profile(...)["accounts"]` | https://gravatar.com/beau (same JSON) | 4 accounts, each `username="beaulebens", verified=True`: `x.com/beaulebens`, `linkedin.com/in/beaulebens`, `github.com/beaulebens`, `instagram.com/beaulebens` | VERIFIED (Gravatar only lists accounts the profile owner attached AND verified — this is the strongest single datum) |
| 4 | The handle `beaulebens` exists as a live public profile on GitHub, Hacker News, Medium | `enumerate_profiles("beaulebens", persona="technical", report=True)` | https://www.github.com/beaulebens · https://news.ycombinator.com/user?id=beaulebens · https://medium.com/@beaulebens | `coverage: checked=10, found=3, not_found=5, inconclusive=2`; found = GitHub, HackerNews, Medium | EXISTENCE-VERIFIED ONLY (a live handle is not proof of identity — see caveat) |
| 5 | Two sites could NOT be checked (do not read the gap as "no account") | same call, `coverage.inconclusive_sites` | n/a (bot-walled) | `inconclusive=["Reddit","Twitter"]` | UNVERIFIED / UNKNOWN (bot wall — pith correctly refuses to guess) |
| 6 | The GitHub profile `github.com/beaulebens` is corroborated as the target (not a handle collision) | `resolve_person("beaulebens", Target(name="Beau Lebens", company="Automattic", website="dentedreality.com.au", anchors={github,x,linkedin,instagram}), persona="technical")` | https://www.github.com/beaulebens (fetched + scored) | `confidence=0.67, profiles=[GitHub ACCEPT], best_channels=["GitHub"]`, signal `BACKLINK`; page body also links `github.com/automattic`, `github.com/woocommerce`, `twitter.com/beaulebens` | CORROBORATED (weak — see caveat on the BACKLINK signal) |
| 7 | Medium / HackerNews profiles under `beaulebens` are the same person | `resolve_person(...)` (same call) | — | NOT returned in `profiles` (only GitHub reached ACCEPT) | UNVERIFIED — I must NOT attribute those to Beau |

## Caveats a journalist must not skip

1. **Identity of the handle ≠ identity of the emailer.** pith proves, from public data,
   that the handle `beaulebens` maps to the public figure Beau Lebens. It does **not**
   prove the person who emailed me controls that handle. Anyone can type a known email
   into a "from" field. Before quoting, I still need an **out-of-band challenge**: ask
   them to post a one-time phrase from the verified `@beaulebens` on X, or push a gist to
   `github.com/beaulebens`. pith gets me to "this handle is really Beau's"; the nonce
   gets me to "the person talking to me is really Beau."

2. **The row-6 corroboration is weaker than its 0.67 looks.** The only signal that fired
   was `BACKLINK`. Inspecting the returned `links`, the match is the GitHub page's own
   canonical URL (`github.com/beaulebens`) intersecting my anchor set — i.e. the page
   referencing itself. The genuinely independent cross-link in the page body,
   `twitter.com/beaulebens`, did **not** score, because my anchor is `x.com/beaulebens`
   and pith normalizes `x.com` and `twitter.com` as different hosts. So treat 0.67 as
   "one live account confirmed present at the expected URL," not "three independent
   signals agree." The `FULL-NAME` signal never fired either — the GitHub page title came
   back as `"beaulebens - Overview"`, not a clean person name.

3. **The real provenance backbone is Gravatar (rows 2–3), not resolve_person.** Gravatar's
   `verified=True` per account is the load-bearing fact: it means the profile owner proved
   control of each linked account. That is a citeable public source and the reason I'd
   trust the handle mapping at all.

## Contact channel (with source)

- **Primary, citeable:** `beau@dentedreality.com.au` — its md5 resolves to the public
  Gravatar `https://gravatar.com/beau` (row 2), so the email↔person link has a public
  source. This is the address that contacted me, and it is publicly corroborated.
- **Verified public profiles for an out-of-band challenge** (row 3, all `verified=True`
  on https://gravatar.com/beau): `https://x.com/beaulebens`,
  `https://www.linkedin.com/in/beaulebens`, `https://github.com/beaulebens`.
  pith's `best_channels` ranked GitHub first.

## Overall call: would I trust this source?

**Handle → identity: YES, with high confidence.** The email resolves to a public Gravatar
for Beau Lebens whose bio matches his known public role, and that Gravatar lists four
owner-verified accounts under `@beaulebens`. Provenance is a single, strong public source
(Gravatar) plus a live GitHub confirmation.

**The emailer → identity: NOT YET.** Nothing pith returned proves the person on the other
end controls those accounts. Before I quote them by name, I will require a one-time-phrase
challenge posted from the verified `@beaulebens` X account or `github.com/beaulebens`.
Until that lands: attribute as "a person using Beau Lebens's publicly verified email,"
not "Beau Lebens said."
