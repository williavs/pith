# Source coverage benchmark — 2026-06-21

Live test of every supported source from a residential IP (home). Each runs the full
pith pipeline (stealth browser → trafilatura markdown). "content" = real public data,
"partial" = identity/metadata but body behind a wall, "blocked" = nothing usable.

## Social / content

| source | verdict | bytes | what comes through |
|---|---|---|---|
| reddit (subreddit) | ✅ content | 44 KB | post titles, text, comments |
| reddit (post) | ✅ content | 7 KB | full post + comments |
| linkedin (company) | ✅ content | 8.5 KB | posts, about |
| linkedin (person) | ✅ content | 38 KB | headline, about, experience, education (+ sign-in modal noise) |
| instagram (profile) | ✅ content | 7.4 KB | bio, captions |
| instagram (post) | ✅ content | 1.4 KB | full caption |
| x / twitter | ✅ content | 3.3 KB | tweet text |
| medium | ✅ content | 2.7 KB | article list + content |
| facebook | 🟡 partial | 786 B | name, follower counts; post body behind login |
| threads | 🟡 partial | 489 B | a post caption, short |

## B2B sales-intel (live public signals)

| source | verdict | bytes | sales signal |
|---|---|---|---|
| trustpilot | ✅ content | 26 KB | reviews + rating — competitor displacement |
| indeed | ✅ content | 3.3 KB | open roles — hiring intent |
| producthunt | ✅ content | 3.5 KB | launches |
| crunchbase | ✅ content | 1.9 KB | funding / firmographics |
| glassdoor | 🟡 partial | 1.2 KB | company overview; reviews partially walled |

## Dropped (stealth browser can't crack the content)

| source | result | note |
|---|---|---|
| g2 | ✗ no content | heavy bot protection |
| wellfound | ✗ no content | — |
| builtwith | ✗ 37 B | needs their API |
| tiktok | ✗ sidebar only | video/caption content not rendered |
| quora | ✗ wall | — |
| pinterest | ✗ placeholder only | — |

## Method note

All blocked sources fail at the TLS-fingerprint / "network security" edge (Reddit:
`server: snooserv`, 403). Plain HTTP — urllib, `requests` (every UA incl. Reddit's
official format), `curl_cffi` browser-TLS impersonation, OAuth — all 403, even from a
clean residential IP. Only a real stealth browser (`scrapling`, Cloudflare-solve +
Google referer) loading the human HTML page works. The reference repos' "no auth needed"
`.json` approach is dead as of 2026-06.
