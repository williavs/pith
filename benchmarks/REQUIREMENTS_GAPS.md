# Lead requirements vs. what the free keyless stack delivers

Measured with `benchmarks/completeness.py` — per-field fill for **POI-only** (Overpass+Overture)
vs **POI + website enrichment** (pith crawls the business's own site). Two categories, n=10 each:
dentists/Phoenix (chain-heavy) and real-estate-agents/Austin (individual-practitioner).

## The requirement (a "full lead") and free-stack fill

| Field | POI only | + website enrichment | Filled by | Verdict |
|---|---|---|---|---|
| name | 100% | 100% | POI | **free** |
| category | 100% | 100% | POI | **free** |
| address | 100% | 100% | POI + site | **free** |
| phone | 100% | 100% | POI + site | **free** |
| website | 100% | 100% | POI | **free** |
| email (any) | 70-80% | **90-100%** | site crawl | **free** — enrichment's main lift |
| owner/named email | 0% | **~40%** | site crawl | **free, partial** |
| socials | 80-90% | 70-90% | Overture + site | **free** |
| linkedin | 0% | 10-30% | site | free, thin |
| decision-maker name+title | 0% | **0-10%** | schema.org Person (rare) | free but rare |
| hours | 0% | 0% | — (not extracted) | gap |
| rating / reviews | 0% | 0% | — | **gap → keyed** |
| employees | 0% | 0% | — | **gap → paid** |
| founded | 0% | 0% | — | **gap → paid** |

## What this means

**The free stack already produces a complete, contactable lead.** Identity + location + phone +
website + an email (named ~40% of the time) + socials. Core fields hit 100% every time; the
website crawl is what turns a thin POI row into a workable lead (+4 owner-emails, +2-3 emails,
+2-3 LinkedIn per 10). No key needed for any of this.

**Decision-maker name+title is thin (0-10%) and it's not a key problem.** Most local sites don't
publish schema.org Person+jobTitle, and — importantly — Yelp/Google keys don't fill this either.
The "who exactly to call" signal comes more from a named email (gene@genearant.com) than a
structured name. Verified person + title + direct line is paid B2B territory (ZoomInfo/Apollo).

## What a (free) API key actually buys you

A Google Places or Yelp Fusion key fills a **different** set than most people expect:

- **rating / review count / hours** — the "is this a good, busy, real business" signal. The free
  stack has none of this. This is the main reason to add a key.
- **coverage + freshness lift** — better phone/website hit-rate where OSM is thin, and fresher
  data (Google is near-real-time vs Overture's monthly snapshot).

A free key does **not** get you decision-maker contacts. If someone tells you "get an API key to
get the contacts," they mean paid B2B data, not Yelp/Google.

## Recommendation

1. **Ship on the free stack for contactable lists.** It's complete for name/address/phone/
   website/email/socials — a sellable/workable list with zero keys.
2. **Add a free Google or Yelp key only if you want rating/reviews/hours** to prioritize leads by
   quality/activity. It's pluggable (`PITH_GOOGLE_KEY` / `PITH_YELP_KEY`) and merges +
   corroborates automatically.
3. **Don't expect any free/keyed source to hand you verified decision-makers.** That's paid.

## Correction — rating/hours/founded/employees are NOT purely keyed/paid

The gap table above (measured before the fix) marked rating/employees/founded as keyed/paid. That
was an artifact of pith's extractor using a prescriptive field allowlist that **dropped**
`aggregateRating`, `openingHours`, `priceRange`, `foundingDate`, `numberOfEmployees`, `geo` from
the JSON-LD. Local businesses often publish these on their own site **for free** — pith just
wasn't looking. Now captured (`pith.extract.firmographics`) and surfaced in the leadgen app:
e.g. a Phoenix dentist yields `rating 5.0 (4)` + `hours Mo-Th 06:00-18:00 …` with no key. So for
storefront businesses these are free-when-published; a keyed API (Yelp/Google) is only needed when
the site itself doesn't publish schema (common for big B2B, rare for local).

- **named people without jobTitle** are extracted but not surfaced as decision-makers (only
  jobTitle-bearing Person entities count). Surfacing all named people as candidate contacts would
  help where the team is listed but not schema-tagged with titles.
