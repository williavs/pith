# `--llms-txt` on real docs sites

Four popular code-docs sites run through `pith --sitemap … --llms-txt`, chosen to exercise both
paths: sites that serve **native `<url>.md`** (pith takes it verbatim, browser-free) and sites that
only serve **HTML** (pith extracts). All keyless, one command each. `--limit 12` for a quick sample;
drop the limit to mirror the whole site.

> Only short excerpts are shown below — the full corpora aren't committed (third-party docs). Run the
> commands to regenerate them yourself.

| Site | Platform | Command (abbrev.) | Result |
|---|---|---|---|
| **Resend** | Mintlify | `--sitemap resend.com/docs/sitemap.xml --match /docs/` | 12 pages — **12 native .md**, 0 extracted |
| **Bun** | custom | `--sitemap bun.sh/sitemap.xml --match /docs/` | 12 pages — **11 native .md**, 1 extracted |
| **FastAPI** | MkDocs | `--sitemap fastapi.tiangolo.com/sitemap.xml` | 12 pages — 0 native, **12 extracted** |
| **Astro** | Starlight | `--sitemap docs.astro.build/sitemap-index.xml --match /en/` | 12 pages — 0 native, **12 extracted** |

Each run also writes `<outdir>/llms.txt` — a complete index (title + local link + description) built
from the **sitemap**, not the site's own (often-partial) llms.txt.

## What the output looks like

**Resend — native `.md` (verbatim, byte-identical to source):**
```
# Add a domain

> Get started sending emails by adding a domain to your account.

Resend sends emails using a domain you own. Before you can send or receive emails …
```

**Astro — extracted from HTML (clean heading + body):**
```
# Components

**Astro components** are the basic building blocks of any Astro project. They are
HTML-only templating components with no client-side runtime and use the `.astro`
file extension.
```

**FastAPI — extracted from MkDocs:**
```
# Environment Variables[¶](https://fastapi.tiangolo.com#environment-variables)

Tip
…
```

## Observations

- **Auto-detection just works.** Same command everywhere; the native/extracted split is decided per
  page. Bun shows the mixed case — 11 pages had a native `.md`, 1 didn't and fell back to extraction,
  in a single run.
- **Native is canonical.** Native pages are written byte-for-byte as the site serves them (verified
  with `diff` on code.claude.com). They do carry whatever preamble the site injects — several
  Mintlify sites prepend a `> ## Documentation Index …` blockquote to every page. That's the source's
  own content; pith doesn't strip it (canonical fidelity over cosmetic cleanup).
- **Extraction is clean.** Headings and prose come through well. One residue: MkDocs leaves its
  heading-anchor permalink in the H1 (`[¶](…)`); harmless, it's a valid link. Titles in `llms.txt`
  are cleaned of the bare `¶`.
- **Coverage is the sitemap's.** Astro's sitemap-index lists 5,800+ locale URLs; `--match /en/` keeps
  English. Always scope big multi-locale sitemaps with `--match`.
