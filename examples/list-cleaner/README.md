# List Cleaner — validate + segment a stale contact list

The "I have 100k old leads — which are still worth selling to?" job. Feed a stale B2B contact list
(Apollo/ZoomInfo-style export: name/title/org/email/phone/linkedin), get back a **cleaned CSV with
deliverability + validity flags and a `quality` tier** you can filter — all deterministic, no LLM,
no paid API, no SMTP probe.

## Why a batch pipeline, not a live app

At 73k–100k rows, a Streamlit grid chokes (and you can't hand-edit 100k anyway). So the work is
split:

- **`clean.py`** — the batch engine. Does the whole file on disk, tiered by cost, writes
  `cleaned.csv` + `<name>.summary.json`. This is where the volume is handled.
- **`dashboard.py`** — a thin Streamlit view over the *cleaned* CSV: summary metrics + charts over
  the full set, filters to the segment you'd actually sell, a **capped preview** (500 rows), and a
  **download of the full filtered segment**. Aggregates + a sample + a download link — never renders
  all the rows.

## Run

```sh
# 1) clean (dnspython is optional — enables the MX deliverability check)
uv run --with pandas --with openpyxl --with dnspython python examples/list-cleaner/clean.py \
    "~/Downloads/your list.xlsx" -o ~/Downloads/cleaned.csv

# 2) explore + export segments
uv run --with streamlit --with pandas streamlit run examples/list-cleaner/dashboard.py
```

`clean.py` flags: `--email-col` (default `email`), `--phone-col` (comma-separated → first non-empty
wins, for Apollo lists with several phone columns), `--website-col` (verify site liveness, optional),
`--workers` (parallel lookups), `--no-trim` (skip the trimmed output), `--limit` (cap rows, testing).

Every run writes **two** files: `<out>.csv` (all rows + validation columns) and
`<out>.trimmed.csv` (the fat cut off — deliverable, deduped contacts you'd actually work).

Example (a rich Apollo export with a Website column + several phone fields):

```sh
python examples/list-cleaner/clean.py "list.xlsx" -o out.csv \
    --email-col Email \
    --phone-col "Work Direct Phone,Mobile Phone,Corporate Phone" \
    --website-col Website
```

## What it validates

| Tier | Cost | Checks |
|---|---|---|
| 1 | offline, every row | email **syntax**, **role** inbox (`info@`), **disposable** domain, **freemail** (gmail/…); phone **valid** + **region** + **line type** + E.164 (`pith.verify_email`, `pith.phone_intel`) |
| 2 | cheap, **deduped by domain** | **domain resolves** (dead-domain detection) + **MX record** (accepts mail). A 73k list = ~24k unique domains — deduping is the whole speedup. |
| 3 | skipped at scale | LinkedIn / company-site / person-still-there — walled + slow; do those on the shortlist you export, not the whole list. |

Output columns added: `email_syntax, is_role, is_disposable, is_freemail, email_domain,
domain_resolves, has_mx, phone_valid, phone_e164, phone_region, phone_line_type,
is_duplicate_email, quality`.

**`quality`** is a transparent tier (filter on it, it's not a black-box score):
- **`sellable`** — valid syntax, not disposable, domain takes mail (MX or resolves), and a business
  inbox (not role/freemail).
- **`risky`** — deliverable but a role (`info@`) or freemail (`gmail`) address — reachable, but not
  the owner's business inbox.
- **`dead`** — bad syntax, disposable, or the domain won't accept mail. Don't send.

## Stage 2 — rank the accounts (`enrich.py`)

Cleaning gets you a deliverable list. `enrich.py` turns it into a **ranked account list**: dedupe
contacts to unique companies, enrich each with pith's signal stack (tech stack, open roles, news
signals, funding), and score for sell-fit — so you work the funded, hiring, growing accounts first.

```sh
uv run --with pandas python examples/list-cleaner/enrich.py ~/hfl-contacts/verified_40k.trimmed.csv \
    -o ~/hfl-contacts/accounts_40k.csv --domain-col email_domain --name-col Company --limit 300
```

- **`--limit N`** enriches the top N companies by contact count. The signal calls (news/jobs) are
  network-bound and slow (~15s/company), so you enrich your *target set*, not all 100k — 300
  companies ≈ 13 min.
- **Checkpointed**: it appends + flushes per company and skips any already in the output, so it's
  safe to Ctrl-C and resume. No lost work, no re-hitting a done company.
- **`score`** is transparent (hiring × 2 + funding + product/AI/leadership news + modern tech) —
  filter/sort on it, it's not a black box.

### Why not a "faster" language for the volume

450k rows is small — pandas handles it in seconds. The slow part is the **network** (walled,
rate-limited enrichment sources), and a faster language does nothing for network-bound work. The
engine is pith, which is Python. The real levers — dedupe-to-companies, checkpoint/resume, bounded
concurrency, enrich-a-shortlist — are all here, in Python.

### Next: LinkedIn freshness (the staleness fix)

A year-old list's biggest risk is people who moved. The rows carry `linkedin_url`; fetching the
**public** LinkedIn page (pith browser tier) gives current company + title — is this person still
there? That's the freshness check. It's walled + slow, so you run it on the **shortlist** you
export from stage 2, not the whole list. (Not built here yet — it's the natural next step.)

## Honest boundaries

- **No SMTP verification.** It's deliberately omitted — SMTP probing is unreliable
  (catch-all/greylisting) and burns sender reputation. `has_mx` (domain accepts mail) + `domain_resolves`
  are the deterministic signals; the actual per-mailbox check is your ESP's job at send time.
- **MX needs `dnspython`** (`pith[email]`). Without it, `has_mx` is `None` and `quality` falls back
  to `domain_resolves` — still catches dead domains, just less precise on parked ones.
- **Staleness ≠ dead.** A resolving domain with MX means the *company* still takes mail; it does not
  prove the *person* is still there. For a Jan-2025 list, the LinkedIn URL + a shortlist recheck is
  the follow-up — this pipeline gets you from 73k raw to the clean, reachable segment first.
- **Phone line type:** phonenumbers can't split mobile vs fixed for US/NANP numbers (reports
  `fixed_or_mobile`); `toll_free` often means a company main line, not a direct dial.
