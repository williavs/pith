# Make any website agent-friendly (`--llms-txt`)

Turn a whole documentation site into a local, agent-ready corpus: one clean markdown file per page
(mirroring the site's URL structure) plus an `llms.txt` index. Keyless — pith is the extraction
engine, so this is the free counterpart to a hosted extract-from-sitemap / llms.txt generator.

## Use

```sh
# a whole doc site from its sitemap (raise --limit to cover everything)
pith --sitemap https://example.com/sitemap.xml --limit 500 --workers 8 --llms-txt ./example-docs

# one section only
pith --sitemap https://example.com/sitemap.xml --match /docs/ --limit 200 --llms-txt ./example-docs

# everything linked from a HUB page (a series index, blog archive, TOC, awesome-list)
pith --links https://example.com/series-index --match /article/ --llms-txt ./series

# no sitemap? crawl from the homepage instead
pith --crawl https://example.com --limit 200 --llms-txt ./example-docs
```

### `--links`: the hub-page source

When the thing you want is "every article this index page links to," use `--links`. It extracts the
hub page, takes its outbound links, keeps those matching `--match`, and fetches each. Real example —
archive Hackaday's *Logic Noise* series (15 posts, one command, no `curl | grep`):

```sh
pith --links "https://hackaday.com/series_of_posts/logic-noise/" --match logic-noise --llms-txt ./logic-noise
```

Every `Result` also exposes `.links` (all outbound URLs on the page) directly, so in Python the
harvest is just `Extractor().extract([hub]).results[0].links`.

**Caveat — pagination.** `--links` reads one page's links. A paginated archive (`/page/2/`, `/page/3/`)
needs either multiple `--links` runs, or harvest the URLs across pages yourself and feed `--from`.

Output:
- `<outdir>/llms.txt` — index: `- [title](local/path.md): description`, one line per page
- `<outdir>/<url-path>.md` — clean markdown, dirs mirror the URL (`/docs/en/hooks` → `docs/en/hooks.md`)

## It's automatic — native markdown when available, extraction when not

You don't choose. Per page, pith first tries the site's **native `<url>.md`** (Mintlify/Fern/Claude
docs serve this) — canonical, byte-for-byte, no browser. If that isn't real markdown (HTML,
soft-404, missing), it **extracts the HTML** instead (browser-escalating only for JS walls). The run
reports the split, e.g. `142 native .md, 21 extracted`.

Two things worth knowing:
- **The sitemap is the source of truth for coverage**, not the site's `llms.txt`. A site's own
  `llms.txt` is often curated/partial, so pith ignores it as an input and *generates* a complete one
  from every sitemap page.
- **No sitemap?** `--crawl` follows links from the homepage instead.

(If you just want the Claude Code docs specifically and they already serve `.md`, the sibling
`claude-docs-mirror` tool fetches them directly on a timer — no extraction needed.)

## Keep it fresh

Same pattern as any scheduled job — a `systemd --user` timer or cron re-running the command a few
times a day keeps the corpus current. See `../../../claude-docs-mirror/` for a worked timer setup.
