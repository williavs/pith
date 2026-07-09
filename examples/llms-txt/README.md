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

# no sitemap? crawl from the homepage instead
pith --crawl https://example.com --limit 200 --llms-txt ./example-docs
```

Output:
- `<outdir>/llms.txt` — index: `- [title](local/path.md): description`, one line per page
- `<outdir>/<url-path>.md` — clean markdown, dirs mirror the URL (`/docs/en/hooks` → `docs/en/hooks.md`)

## When to use pith vs. the site's own markdown

Check first — many modern doc sites already serve markdown natively (a `/llms.txt` index and a
`<url>.md` for every page). If they do, just fetch those; it's canonical and cheaper than
re-extracting HTML. (That's how the sibling `claude-docs-mirror` tool works — the Claude Code docs
serve `.md` directly.)

Reach for `pith --llms-txt` when the site **only gives you HTML** — no `llms.txt`, no `.md`
endpoints. pith renders each page (escalating to a real browser only for JS-walled pages) and
produces the markdown corpus the site didn't hand you.

## Keep it fresh

Same pattern as any scheduled job — a `systemd --user` timer or cron re-running the command a few
times a day keeps the corpus current. See `../../../claude-docs-mirror/` for a worked timer setup.
