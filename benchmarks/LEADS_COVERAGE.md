# pith.leads — Coverage & Reliability (measured)

What `find_businesses()` actually returns from the two keyless providers, measured on a
4-category x 3-city matrix. Every number below is from a real run; the raw data is in
`benchmarks/leads_coverage.json` and reproducible with `benchmarks/leads_coverage.py`.

## Method

- Categories: `dentists`, `restaurants`, `plumbers`, `gyms`
- Cities: `Phoenix, AZ`, `Austin, TX`, `Portland, OR`
- `radius_km=3` (small bbox → fast Overture download), `limit=100`, geocode via Nominatim.
- **Overpass (OSM live) ran on all 12 cells.** Overpass is fast and stdlib-only.
- **Overture ran on the 4 Phoenix cells only** (one per category). Each Overture call downloads
  and filters a bbox tile (~15-90s), so the sweep restricts it to Phoenix to control cost.
- Per cell we ran each provider alone (its own yield) plus a merged `sources="auto"` run for the
  cross-source numbers. Cells were wrapped in try/except; the sweep recorded 0 unrecovered errors.

Because Overture only ran on Phoenix, the **8 non-Phoenix cells are Overpass-only** — their
"merged" row is identical to their Overpass row, and cross-source agreement is structurally 0
there (only one provider present). Treat agreement numbers as meaningful for the 4 Phoenix cells only.

### Operational note: the free Overpass endpoint throttles

During this run the public `overpass-api.de` endpoint returned `HTTP 429 (Too Many Requests)`
or `HTTP 504 (Gateway Timeout)` on 8 of the cells' first attempts. A lone spaced request
succeeds; several within a few seconds trip a per-IP cooldown. The benchmark clears this with
retry + growing backoff (15/30/45s); most cells recovered on the first retry, one (plumbers
Portland) needed three. This matches Overpass's own metadata string: *"continuous... no SLA."*
If you call `find_businesses` with the `overpass` provider in a tight loop, budget for retries.

## Per-cell yield (measured)

`count` = merged/deduped businesses. `%web / %phone / %email` = fraction of that provider's
records carrying the field. Overpass ran on every cell; Overture only where shown.

### Overpass (OSM, all 12 cells)

| category | city | count | %web | %phone | %email |
|---|---|--:|--:|--:|--:|
| dentists | Phoenix, AZ | 3 | 0.0 | 0.0 | 0.0 |
| dentists | Austin, TX | 21 | 33.3 | 33.3 | 14.3 |
| dentists | Portland, OR | 29 | 89.7 | 65.5 | 6.9 |
| restaurants | Phoenix, AZ | 100 | 41.0 | 43.0 | 2.0 |
| restaurants | Austin, TX | 100 | 55.0 | 33.0 | 4.0 |
| restaurants | Portland, OR | 100 | 79.0 | 54.0 | 4.0 |
| plumbers | Phoenix, AZ | 3 | 0.0 | 0.0 | 0.0 |
| plumbers | Austin, TX | 0 | 0.0 | 0.0 | 0.0 |
| plumbers | Portland, OR | 0 | 0.0 | 0.0 | 0.0 |
| gyms | Phoenix, AZ | 9 | 66.7 | 44.4 | 0.0 |
| gyms | Austin, TX | 21 | 28.6 | 33.3 | 0.0 |
| gyms | Portland, OR | 25 | 80.0 | 32.0 | 4.0 |

(`restaurants` hit the `limit=100` cap in all three cities — raw pre-cap counts were 128/292/296.)

### Overture (Phoenix only, 4 cells)

| category | city | count | %web | %phone | %email |
|---|---|--:|--:|--:|--:|
| dentists | Phoenix, AZ | 29 | 96.6 | 96.6 | 58.6 |
| restaurants | Phoenix, AZ | 100 | 95.0 | 100.0 | 66.0 |
| plumbers | Phoenix, AZ | 0 | 0.0 | 0.0 | 0.0 |
| gyms | Phoenix, AZ | 53 | 81.1 | 83.0 | 60.4 |

### Merged (both sources where available)

| category | city | count | %web | %phone | %email | agree% | mean_conf | sources |
|---|---|--:|--:|--:|--:|--:|--:|---|
| dentists | Phoenix, AZ | 31 | 90.3 | 90.3 | 54.8 | 3.2 | 0.660 | overpass+overture |
| dentists | Austin, TX | 21 | 33.3 | 33.3 | 14.3 | 0.0 | 0.412 | overpass |
| dentists | Portland, OR | 29 | 89.7 | 65.5 | 6.9 | 0.0 | 0.412 | overpass |
| restaurants | Phoenix, AZ | 100 | 96.0 | 100.0 | 68.0 | 43.0 | 0.752 | overpass+overture |
| restaurants | Austin, TX | 100 | 55.0 | 33.0 | 4.0 | 0.0 | 0.412 | overpass |
| restaurants | Portland, OR | 100 | 79.0 | 54.0 | 4.0 | 0.0 | 0.412 | overpass |
| plumbers | Phoenix, AZ | 3 | 0.0 | 0.0 | 0.0 | 0.0 | 0.412 | overpass+overture |
| plumbers | Austin, TX | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | overpass |
| plumbers | Portland, OR | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | overpass |
| gyms | Phoenix, AZ | 57 | 78.9 | 78.9 | 56.1 | 8.8 | 0.618 | overpass+overture |
| gyms | Austin, TX | 21 | 28.6 | 33.3 | 0.0 | 0.0 | 0.412 | overpass |
| gyms | Portland, OR | 25 | 80.0 | 32.0 | 4.0 | 0.0 | 0.412 | overpass |

## Per-source rollup (measured, weighted by record count)

| source | cells | records | %web | %phone | %email |
|---|--:|--:|--:|--:|--:|
| Overpass (OSM) | 12 | 411 | ~58 | ~43 | ~4 |
| Overture | 4 (Phoenix) | 182 | ~91 | ~95 | ~63 |

Overture carries contact fields on nearly every record; Overpass carries a website on a bit
over half and an email on almost none. The gap is largest on **email** (Overture ~63% vs OSM ~4%)
and clear on **phone** (Overture ~95% vs OSM ~43%).

## Source metadata (exact strings from `coverage.source_meta`)

The registry exposed 6 providers at run time; only the two keyless ones (`overpass`, `overture`)
were available and ran. The four keyed providers were present in metadata but skipped (no key).

**overpass** (`needs_key: false`, ran)
- update_frequency: `continuous (crowdsourced; minute-level edits, no SLA)`
- reliability: `existence/location strong; contact tags ~30% present; trades thinner than storefronts`
- license: `ODbL (attribution + share-alike)`

**overture** (`needs_key: false`, ran)
- update_frequency: `monthly release (Linux Foundation; ~25 data partners)`
- reliability: `confidence-scored + source lineage; broadest coverage; phone/website richer than OSM`
- license: `CDLA-Permissive 2.0 (commercial-clean, no share-alike)`

**fsq_open** (`needs_key: false`, not run — needs the `pith[places]` DuckDB path)
- update_frequency: `monthly release (Foundry/Foursquare open data on Hugging Face)`
- reliability: `~100M global POIs; strong urban coverage; category-rich`
- license: `Apache-2.0 (commercial-clean)`

**yelp** (`needs_key: true`, not run)
- update_frequency: `live API (Yelp-maintained; near real-time)`
- reliability: `strong US SMB coverage, phone + address + ratings; no website/email in payload`
- license: `Yelp Fusion ToS — display use; storing/reselling restricted`

**google** (`needs_key: true`, not run)
- update_frequency: `live API (Google Places, New; best freshness)`
- reliability: `highest completeness + freshness; phone + website + address`
- license: `Google Places ToS — caching limited, storing/reselling restricted`

**fsq_api** (`needs_key: true`, not run)
- update_frequency: `live API (Foursquare Places; near real-time)`
- reliability: `global POIs, category-rich; phone + website + address`
- license: `Foursquare Places API ToS — attribution; storage limited`

## What's strong, what's weak

### By category
- **restaurants — strong.** Both sources returned the full 100-cap in all three cities (raw
  128-296 before the cap). Highest contact coverage: Overture Phoenix hit 95% website / 100% phone,
  and it's the only category where cross-source agreement was high (43%). Storefronts are dense in
  OSM and Overture alike.
- **dentists — medium, metro-dependent.** OSM density swung from 29 (Portland, 90% website) and
  21 (Austin, 33% website) down to just 3 (Phoenix). In Phoenix, Overture rescued the cell: 29
  records at 96.6% website/phone. If you only ran Overpass in Phoenix you'd have seen 3 dentists.
- **gyms — medium.** OSM returned 9 (Phoenix) / 21 (Austin) / 25 (Portland); Overture found 53 in
  the same Phoenix bbox. Contact coverage on OSM gyms is uneven (phone 32-44%, email ~0).
- **plumbers — weak everywhere.** OSM: 3 / 0 / 0 across the three cities. Overture Phoenix: **0**.
  Merged total across all three cities: 3. Trades that operate without a storefront are essentially
  invisible in keyless POI data — this confirms the "trades thinner than storefronts" hypothesis
  with hard zeros, not a hunch. For plumbers/roofers/HVAC/electricians, expect a keyed provider
  (Yelp/Google) or a different data source; the keyless path will not find them.

### By source
- **Overpass (OSM):** strong on existence + storefront density, free, live, stdlib-only, no key.
  Weak on contact completeness (email ~4% overall), highly variable by metro (Phoenix core came
  back sparse for professional/trade categories), thin on trades, and the public endpoint throttles
  under load. Best as a fast, free breadth pass for storefront categories.
- **Overture:** strong on contact fields (website ~91%, phone ~95%, email ~63%) and it carries a
  confidence score. Weak on trades (plumbers 0), it's a monthly snapshot (not live), each query is
  a 15-90s bbox download, and it needs the `overturemaps` dependency. Best as the enrichment/
  contact layer over Overpass's breadth.

## Cross-source agreement & confidence

Agreement (`corroboration > 1`, i.e. a business attested by more than one provider) is only
measurable on the 4 Phoenix dual-source cells:

- restaurants: 43/100 = **43.0%**
- gyms: 5/57 = **8.8%**
- dentists: 1/31 = **3.2%**
- plumbers: 0/3 = **0.0%**
- Pooled across the 4 Phoenix cells: **49 / 191 = ~25.7%** of merged records were corroborated by
  both OSM and Overture.

Agreement is low outside restaurants. Two reasons visible in the data: (1) OSM density is thin for
dentists/gyms/plumbers in the Phoenix core, so there are few OSM records for Overture to match
against; (2) the merge keys on normalized name + ~150m proximity (or a shared phone/website), and
storefront chains (restaurants) match far more reliably than independently-named clinics or gyms.
A corroborated record is genuinely more trustworthy, but **low agreement here mostly reflects OSM's
sparse coverage of these categories, not conflicting data.**

**What confidence means (from `_merge_cluster`):** confidence is a transparent blend, not a hidden
score. `conf = 1 - 1/(1 + w)` where `w` sums provider reliability weights (overpass 0.7, overture
0.85), with an upward nudge toward Overture's own per-record confidence when present. Concretely,
the values you'll see:
- **0.412** = seen by Overpass only (`1 - 1/1.7`). This is every single-source OSM cell above.
- **0.0** = no record (empty cell).
- **~0.46-0.75** = Overture present (its own confidence score pulls the number up) and/or both
  providers agree. The two-source cells landed at 0.618 (gyms), 0.660 (dentists), 0.752
  (restaurants). Higher = more independent corroboration and/or a high Overture confidence.

So confidence is chiefly a *corroboration + source-quality* signal. A 0.41 record is "one free
source saw this"; a 0.7+ record is "two sources agree, or Overture is highly confident."

## How often is this updated / how reliable is it?

Grounded in what was measured: the two keyless sources update on very different clocks. **Overpass
is continuous** — OSM edits land within minutes and are served live, so newly-added or newly-edited
businesses appear immediately, but there is no SLA and the public endpoint returned 429/504 on ~8
of our calls (recoverable with backoff). **Overture is a monthly snapshot** from ~25 data partners,
so it lags reality by up to a release cycle but is far more complete on contact fields (website ~91%,
phone ~95%, email ~63% vs OSM's ~58/43/4). Reliability of *existence* is good on both for storefront
categories (restaurants filled the cap everywhere); reliability drops sharply for **trades**
(plumbers returned 3 records total across three cities, 0 from Overture) and for any category in a
metro where OSM tagging is sparse (Phoenix dentists: 3 from OSM, 29 from Overture). Net: for keyless
lead discovery, treat Overpass as the free live breadth pass and Overture as the monthly
contact-enrichment layer; expect strong results for storefronts, weak-to-empty results for trades,
and add a keyed provider (Yelp/Google) when you need trades or guaranteed freshness.
