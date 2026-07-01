# SDR target-account list (pith)

Prospecting run for a developer-productivity SaaS. Goal: take 8 real dev-tool companies by
domain, enrich each with pith, and rank by fit (reachability + relevance).

## What I did

1. Picked 8 ICP accounts by domain: Stripe, Linear, Vercel, Notion, Retool, Airtable, Figma, Ramp.
2. Ran `build_leads.py` — for each account:
   - `enrich_company(name, website)` → firmographics: LinkedIn/GitHub/Twitter, company-matched emails, careers-page flag, tech grade.
   - `website_intel(website)` → framework, responsive, domain age, dated signals.
3. Scored fit and wrote the ranked `leads.csv`, plus `account-plan.md` for the top 3.

### pith calls used
- `pith.cli.enrich_company` — the workhorse; one call per account returns a GTM-ready dict.
- `pith.cli.website_intel` — tech-stack + domain age, merged in for extra columns.

### Fit score
`reachability` (company email = +2, LinkedIn +1, Twitter +1) + `relevance` (careers page +2, public GitHub +1). Higher = hotter.

## Run it

```bash
.venv/bin/python examples/personas/sdr/build_leads.py
```

Outputs `leads.csv` (ranked) and `leads_raw.json` (full dicts).

## What the data looked like (real output)

| rank | company | fit | grade | emails found | careers | github |
|---|---|---|---|---|---|---|
| 1 | Stripe | 7 | A | 5 (incl. sales@, careers@) | y | y |
| 2 | Linear | 6 | A | 2 (sales@, hello@) | y | y |
| 3 | Vercel | 5 | A | 0 | y | y |
| 4 | Retool | 5 | A | 1 (support@) | y | - |
| 5 | Notion | 4 | A | 0 | y | - |
| 6 | Airtable | 4 | A | 0 | y | - |
| 7 | Figma | 2 | A | 0 | - | - |
| 8 | Ramp | 1 | A | 0 | - | - |

Highlights:
- **Stripe** was the only account with a rich email set (5), including a usable `sales@stripe.com`.
- **Linear** gave the cleanest founder-reachable emails (`hello@linear.app`).
- All 8 graded **A** — every one is a modern Next.js site, so grade added no ranking signal here.

## Honest friction (DX notes for the pith team)

1. **`domain_age_years` is misleading as a firmographic.** It reports WHOIS *registration* age, not company age. Ramp came back 32 yrs, Retool 29, Vercel 27, Figma 27 — all companies <12 yrs old that bought pre-existing domains. As an SDR I'd read that column as "old established company" and be wrong every time. It's WHOIS truth, but mislabeled for this use.
2. **`enrich_company` emails are an untyped flat list.** `find_contact` types emails (owner/role/person) and ranks them; `enrich_company` does not — I just get a list. So my "primary email" for Stripe auto-picked `accommodations@stripe.com` (an ADA/hiring mailbox), the single worst choice. For B2B I need the owner/role ranking exposed here too, or a `primary_email` field that isn't just `emails[0]`.
3. **LinkedIn false-negatives.** Linear and Retool both have public LinkedIn company pages, but `enrich_company` returned no LinkedIn for them (the name-token matcher missed non-exact paths like `/company/notionhq`). GitHub matched fine; LinkedIn was the weak one.
4. **`grade` doesn't discriminate for tech prospecting.** All 8 = A. The modernness grade is clearly tuned for spotting dated small-biz sites (its `build_sales_list` origin), not for ranking infra companies. Not a bug, but for this ICP the headline `website_intel` feature is dead weight.
5. **Inconsistent social normalization.** Twitter URLs came back mixed `twitter.com/...` and `x.com/...` across accounts. Minor, but a CRM dedupe would treat them as different.
6. **No firmographics that an SDR actually sorts on** — headcount, funding, industry, HQ. pith gives contactability + tech, which is real, but a sales list usually needs size/segment to prioritize, and that isn't derivable from the site here.

Net: pith is genuinely useful for the *reachability* half of a lead list (emails + socials + careers signal, deterministic, fast). The *firmographic* half (company age, size, segment) is either missing or mislabeled, and `enrich_company`'s email output needs the same typing `find_contact` already has.
