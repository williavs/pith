# PITH Lead Miner

A Win98-flavored lead-gen + enrichment workbench built on `pith.leads` (multi-source business
discovery) and pith's extraction core (contact + tech enrichment).

**Two clicks to a list:** pick a category + a location, hit **MINE**. pith pulls real local
businesses from every configured source and waterfall-merges them — each row shows which sources
agree (`overpass+overture`) and a confidence score. Then select rows and **ENRICH**: pith crawls
each business's website for emails/phones and fingerprints its tech stack, growing the grid.
**Export CSV** when you're done.

## Run

```sh
# from the repo root
uv run --with streamlit --with overturemaps streamlit run examples/leadgen/app.py
```

Then open http://localhost:8501.

- `--with overturemaps` enables the Overture provider (the second keyless source). Drop it to run
  Overpass-only (still works, just OSM).
- Website enrichment (contact evidence) uses pith's fetch tiers — install the browser extra for
  walled sites: `uv sync --extra js && uv run scrapling install` (optional; most small-biz sites
  don't need it).

## Sources

Keyless out of the box: **overpass** (OSM, live) and **overture** (Overture Maps, bulk). Add a
free key to light up more — they merge + corroborate automatically:

| Provider | Enable with |
|---|---|
| Yelp Fusion | `export PITH_YELP_KEY=…` |
| Google Places | `export PITH_GOOGLE_KEY=…` |
| Foursquare Places | `export PITH_FSQ_KEY=…` |
| Foursquare Open (bulk) | download a release, `export PITH_FSQ_PARQUET=/path/to/places/parquet` |

More sources = more corroboration = higher-confidence rows. See `benchmarks/LEADS_COVERAGE.md`
for measured per-source coverage and reliability.

## How it's built

The mining + enrichment logic is plain functions — `mine_leads`, `enrich_contacts`,
`enrich_tech` — so it's testable without the UI (`tests/test_leadgen_app.py`). Streamlit is just
the shell. `pith.leads.find_businesses` does the geocode → per-source query → waterfall merge;
`pith.cli.contact_evidence` / `website_intel` do the enrichment.
