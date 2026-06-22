# Full source coverage — 2026-06-22

Every candidate hit with a real public URL through the full pith pipeline. Verdicts are
from actual output, not claims. `content` = real public data, `partial` = identity/wall,
`error`/`blocked` = nothing usable. This is the source of truth for the README table.

```
✓ content  reddit         social     45199B   5.6s  [Pycon US 2025 ](https://us.pycon.org/2025/) starts next wee
✓ content  linkedin_co    social      8486B   2.9s  Summer, summer, summertime ☀️ June 21 is the summer solstice
✓ content  linkedin_pers  social      3271B   3.8s  ## Chair, Gates Foundation and Founder, Breakthrough Energy 
~ partial  instagram      social       957B   3.6s  Instagram Log In Sign Up nasa Verified Options 104M follower
✓ content  x              social      3327B   6.2s  The official FIFA World Cup ball went to space! We're workin
~ partial  facebook       social       812B   9.1s  Facebook Log In Log In Forgot Account? NASA - National Aeron
~ partial  threads        social       489B   7.3s  Moon Joy June artists! Check out Luca’s OOTD 👀 The prompt fo
✓ content  medium         social      2697B   3.2s  InSignal v. NoisebyDHH·Feb 11, 2019Signal v Noise exits Medi
✓ content  crunchbase     b2b         1936B   3.9s  Total Funding 99 72 Total FundingSecondary Market raised Gro
✓ content  indeed         b2b         3274B   2.6s  Stripe is a financial infrastructure platform for businesses
✓ content  producthunt    b2b         3492B   5.9s  # Notion ## The all-in-one workspace [4.8](https://www.produ
✓ content  trustpilot     b2b        21641B   4.8s  This is just too complicated! Its too hard for a small busin
✓ content  glassdoor      b2b         1996B   2.9s  Get tailored insights about working at Stripe in one quick s
✓ content  arxiv          public      4108B   0.1s  # Computer Science > Computation and Language [Submitted on 
✓ content  github         public     12814B   0.7s  The fun, functional and stateful way to build terminal apps.
✓ content  guardian       news        5108B   0.3s  Skip to main content Skip to navigation Print subscriptions 
✓ content  bbc            news        2417B   0.5s  ## Listen The Interface UK teens banned from social media, A
✓ content  substack       news        3078B   0.7s  The Pragmatic Engineer Subscribe Sign in Home Podcast The Pu
~ partial  nytimes        paywall      267B   0.5s  [Tech Workers Maxed Out Their A.I. Use. Now They’re Trying t
✗ error    bloomberg      paywall        0B   0.2s  HTTP Error 403: Forbidden
✗ error    wsj            paywall        0B   0.2s  HTTP Error 401: HTTP Forbidden
✓ content  ft             paywall     3438B   0.7s  Triple C score puts Elon Musk’s company on par with Russia a
```

## Notes
- Bloomberg (CAPTCHA) and WSJ (401) fail even through the stealth browser — hard anti-bot, not just static.
- NYTimes returns headline/links only; the article body is paywalled (browser doesn't help).
- Instagram is flaky: full bio+captions usually, a login wall on some fetches (retry mitigates, not cures).
- The 'paywall ✓ 13/13' table that briefly appeared in the README was never run — these are the real numbers.
