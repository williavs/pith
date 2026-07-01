# Agency-founder persona — dated-site lead list

Solo web-agency founder cold-calling small businesses. Best leads = established
local shops with **dated, low-grade websites** (the pitch hook) where I can reach
the **owner** directly. This dir is a real run of that job over `pith`.

## What I did

1. `directory_search(category, "Wichita, KS", limit=20)` for three cold-call-friendly
   trades: **roofing, plumbers, hvac**. One query each.
2. Deduped by domain, dropped listings with no website → **23 unique businesses**.
3. `website_intel(url)` on all 23 → modernness grade + `dated_signals`.
   Kept only **grade C/D/F** → **8 dated sites**.
4. `find_contact(url)` on all 8 dated → email / phone / socials, ranked by owner
   reachability. Top 5 → `opportunities.json`.

Run it yourself:
```
.venv/bin/python examples/personas/agency-founder/build.py
```

## pith calls used
- `from pith.cli import directory_search, website_intel, find_contact`
- `directory_search` returns `[{name, website, address, ...}]` (YellowPages + Superpages scrape).
- `website_intel` returns `{modernness_grade, modernness_score, dated_signals, responsive, https, builder, framework, domain_age_years, copyright_year, ...}`.
- `find_contact` returns `{emails:[{email,type}], phones:[{number,sources}], socials:[url], people, addresses, whois}`.

## What the data looked like

The trades split cleanly into modern vs. dated:
- **Modern (skip):** WordPress/Wix/GoDaddy-built, responsive, grade A (88–100). Burwell,
  Herzberg, Benjamin Franklin, Drainiacs, etc.
- **Dated (my leads):** all landed at **grade D / score 55**, flagged
  `not-responsive` and/or `http-only`. That's the entire pitch surface for this segment.

Top 5 opportunities (see `opportunities.json`):

| Business | Trade | Grade | Dated signal | Domain age | Owner contact |
|---|---|---|---|---|---|
| Absolute Remodeling | roofing | D | not-responsive, http-only | 4y | kendra@… + phone + FB/IG |
| Tailored Roofing & Remodeling | roofing | D | not-responsive | 6y | keganbostick@… + phone + FB |
| Bowers Plumbing | plumbers | D | not-responsive | 17y | phone + FB/IG (no email) |
| David Lies Plumbing | plumbers | D | not-responsive, http-only | 20y | phone only |
| Denny's Heating & Cooling | hvac | D | not-responsive, http-only | 7y | none scraped |

The two roofers gave the best leads: a **personal owner email** on the domain plus a
phone and live social profiles — exactly "reachable + dated."

`outreach.md` has a one-line cold-open per lead, each tied to that site's real
detected weakness (mobile / no-HTTPS).

## Honest notes on the data
- Every dated site scored an identical **55/D** — the grade separates modern from
  dated but gives no spread *within* dated, so I ranked by reachability instead.
- `builder`/`framework` were `unknown`/`null` for nearly every small-biz site — low
  signal for this segment; the useful fields were `dated_signals` + `domain_age_years`.
- Contact scraping thinned out fast: only 2 of 5 leads had a scraped email; the rest
  are phone/cold-call opens.
