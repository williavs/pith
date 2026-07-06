# PITH Account Intelligence (B2B)

B2B account enrichment over the full pith stack. Different from the local lead-miner: here you
bring **target-account domains** and pith assembles the signals a B2B seller needs to prioritize.

**The reliable signals** (work on any company with a domain):
- **hiring** — open roles + which departments + ATS (growth signal; *what* they're building)
- **news** — tagged counts: funding / leadership / product / ai / security (why-reach-out-now)
- **tech** — stack + modernness (competitor detection; AI-services fit)
- **funding** — latest raise (SEC Form D) or public financials
- **firmographics** — industry / employees / founded / HQ (needs a Wikidata entry)
- **contact** — general email / phone

**A lens** reorders what matters:
- `payroll` → headcount + hiring velocity + funding (can they pay, are they growing)
- `ai_services` → tech stack + eng/AI hiring + AI product news + funding
- `generic` → everything

## Run

```sh
uv run --with streamlit streamlit run examples/b2b/app.py
```

Paste domains (or `Name,domain`), one per line. Pick a lens. Enrich. Export CSV.

## Honest boundaries

- **No decision-maker column.** Measured on real B2B accounts: free website extraction of execs is
  noise on large companies (blog authors, customer logos, and advisors pollute the crawl). B2B
  decision-makers are LinkedIn / paid-B2B territory. (Website people extraction *is* reliable on
  small local businesses — the leadgen app keeps that column.)
- **Firmographics need Wikidata** — many private companies aren't in it, so employees/founded/HQ
  are often blank. Hiring + news + tech + funding do not depend on Wikidata.
- **Funding is best-effort** — Form D matching is name-scoped; it can miss or under-count rounds
  for common company names.

The engine (`enrich_account`) is UI-free and tested in `tests/test_b2b_app.py`.
