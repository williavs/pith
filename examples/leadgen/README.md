# PITH Lead Miner

A Win98-flavored lead-gen + enrichment workbench built on `pith.leads` (multi-source business
discovery) and pith's extraction core (contact + tech enrichment).

**Two clicks to a list:** pick a category + a location, hit **MINE**. pith pulls real local
businesses from every configured source and waterfall-merges them — each row shows which sources
agree (`overpass+overture`) and a confidence score. Then select rows and **ENRICH**: one crawl of
each business's site fills owner/role emails, the **decision-maker** (name + title from the team
page), extra phones, socials, and — free from the site's own schema — **rating, reviews, and
hours**, plus a tech-stack grade. **Export CSV** when you're done.

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

## Lessons learned (read before you judge the output)

Field notes from building + stress-testing this. Most "bad results" are one of these, not a bug:

- **Category coverage is wildly uneven.** Storefronts — `dentists`, `restaurants`, `salons`,
  `veterinarians`, `gyms`, `cafes` — are densely mapped and publish rich schema (rating/hours),
  so they enrich beautifully. **Trades** (`plumbers`, `roofers`) and **individual-agent** niches
  (`realtors`) are thin: they're home-based or share IDX/MLS sites, so OSM/Overture have few of
  them and fewer websites. Pick storefronts for strong results. Numbers in
  `benchmarks/LEADS_COVERAGE.md` and `benchmarks/REQUIREMENTS_GAPS.md`.
- **"No site" is not a failure.** A lead with no website can't be crawled — nothing to enrich. The
  `enriched` column says `no site` for those; that's honest coverage, not breakage. Use the
  **Has website** sidebar filter (or sort by the `website` column) before enriching.
- **Decision-maker extraction is reliable on small sites, noisy on big/multi-brand ones.** A local
  dentist's team page → real people. A realty/brokerage/franchise site → the `decision_maker`
  column fills with brand/MLS names (Coldwell Banker, Century 21). This is the deterministic,
  no-LLM ceiling — the site lists dozens of orgs and there's no model to disambiguate.
- **rating / hours / founded are FREE for storefronts** — they come straight from the business's
  own `schema.org` (LocalBusiness), not a paid API. If they're blank, the site just didn't publish
  schema (common for big B2B, rare for local). Don't reach for a Yelp key until you've confirmed
  the gap.
- **Cranking concurrency does NOT speed enrichment.** Measured: 3 sites-at-once = 24.8s, 12 = 36.5s,
  24 = 36.5s — it plateaus and low can even win. Enrichment is CPU-bound (Python's GIL serializes
  the HTML parsing) and the wall time is floored by the single slowest **browser-tier** site, not
  the thread count. The Parallel-enrich slider is there to *see* this, not to fix it. The real
  levers are the per-site **timeout** (capped at 20s so one Cloudflare site can't stall the batch)
  and accepting that JS-rendered sites are just slow.
- **The fetch is already adaptive** — cheap HTTP tier first, the stealth browser only when a page
  comes back empty but has substantial HTML (a real JS shell). It goes deep only when it must.

### Streamlit gotchas (if you fork the UI)

- **Data limits:** never dump an unbounded log/table into one widget — the websocket has a message
  size cap. The log firehose shows a bounded tail over a ring buffer; full lead data stays in
  `session_state` while the grid virtualizes the scroll.
- **Worker threads must not touch `st.session_state`** (no ScriptRunContext). Bind a plain-list
  reference *before* the thread and mutate that; poll it from the main thread for live updates.
- **Custom themes + `st.selectbox`:** the open dropdown menu renders in a separate baseweb popover
  layer — style `[role="option"]`/`[role="listbox"]` (stable ARIA roles), not `data-baseweb` attrs
  (which churn between versions). `accept_new_options=True` makes a dropdown typeable.
