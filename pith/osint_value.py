"""GTM value map for profile enumeration. We enumerate the PERMISSIVE default (every site
except adult) — the long tail carries real signal: a Chess/Strava/Letterboxd profile is a
personalized-outreach hook, StackOverflow/Kaggle/Dev.to are firmographic for technical
buyers, ProductHunt/Gumroad for founders. This map TAGS the ones we recognise (firmographic
= professional identity, psychographic = interests/personality) so results rank + route;
untagged sites still surface as "other", never dropped.

`recency` sites are where fresh activity = a buying-intent / conversation signal.
Refine empirically: run on real people, watch the output, adjust tags.
"""

# name (osint_sites.json key) -> (kind, value, recency_matters, what_you_get)
GTM_SITES = {
    # --- firmographic: who they are professionally ---
    "LinkedIn":    ("firmographic", "high", False, "role, company, tenure, education"),
    "GitHub":      ("firmographic", "high", True,  "technical role, employer in bio, projects, activity"),
    "Keybase":     ("firmographic", "high", False, "cryptographically-linked accounts — identity corroboration"),
    "DEV Community": ("firmographic", "high", True, "engineering writing + technical identity"),
    "Gravatar":    ("firmographic", "med",  False, "bio + linked profiles (aggregator)"),
    "AboutMe":     ("firmographic", "med",  False, "bio, role, curated links"),
    "GitLab":      ("firmographic", "med",  True,  "dev projects, employer"),
    "Codeberg":    ("firmographic", "med",  True,  "dev projects"),
    "BitBucket":   ("firmographic", "med",  False, "dev repos"),
    "Kaggle":      ("firmographic", "med",  True,  "data-science skill + competitions"),
    "Codeforces":  ("firmographic", "med",  True,  "competitive-programming skill"),
    "LeetCode":    ("firmographic", "med",  False, "interview-grind signal (job-seeking?)"),
    "HackerRank":  ("firmographic", "med",  False, "dev skill"),
    "Codepen":     ("firmographic", "med",  True,  "front-end work samples"),
    "CodeSandbox": ("firmographic", "med",  True,  "front-end work samples"),
    "Docker Hub":  ("firmographic", "med",  False, "devops / published images"),
    "ProductHunt": ("firmographic", "med",  True,  "founder/maker, product launches"),
    "Gumroad":     ("firmographic", "med",  True,  "sells a product — solo founder/creator"),
    "Behance":     ("firmographic", "med",  True,  "design portfolio (creative buyers)"),
    "Dribbble":    ("firmographic", "med",  True,  "design portfolio (creative buyers)"),
    "ArtStation":  ("firmographic", "med",  True,  "3D/game-art portfolio"),
    "Carbonmade":  ("firmographic", "med",  False, "portfolio site"),
    "Carrd":       ("firmographic", "med",  False, "personal one-pager (links + role)"),
    "Wikipedia":   ("firmographic", "low",  False, "notable enough to have a page"),
    # --- psychographic: how they think / what they care about (RRM hooks) ---
    "Twitter":     ("psychographic", "high", True,  "opinions, interests, engagement; recency = intent"),
    "Reddit":      ("psychographic", "high", True,  "unfiltered interests, pain points, questions asked"),
    "HackerNews":  ("psychographic", "high", True,  "technical opinions, what they engage with"),
    "Medium":      ("psychographic", "high", True,  "thought-leadership topics they write about"),
    "Substack":    ("psychographic", "high", True,  "writing + subscriber interests"),
    "Bluesky":     ("psychographic", "med",  True,  "opinions/interests (newer network)"),
    "Instagram":   ("psychographic", "med",  True,  "lifestyle, personal interests"),
    "YouTube":     ("psychographic", "med",  True,  "content interests"),
    "TikTok":      ("psychographic", "med",  True,  "content interests"),
    "Twitch":      ("psychographic", "med",  True,  "streaming interests / community"),
    "Blogger":     ("psychographic", "med",  True,  "personal writing"),
    "WordPress":   ("psychographic", "med",  True,  "personal blog / interests"),
    "Letterboxd":  ("psychographic", "med",  True,  "film taste — a genuine personal hook"),
    "Chess":       ("psychographic", "med",  False, "chess player — a personal hook"),
    "Strava":      ("psychographic", "med",  True,  "runner/cyclist — a personal hook"),
    "Pinterest":   ("psychographic", "low",  False, "aspirations/interests"),
    "Untappd":     ("psychographic", "low",  False, "craft-beer hobby"),
    "Trakt":       ("psychographic", "low",  False, "tv/film watching"),
    "Duolingo":    ("psychographic", "low",  False, "learning a language"),
    "Patreon":     ("psychographic", "low",  False, "creators/causes they support"),
}

# persona -> the sites that matter most for that buyer (right sites for the right people)
PERSONA_ROUTES = {
    "technical": ["GitHub", "GitLab", "Codeberg", "DEV Community", "HackerNews", "Kaggle",
                  "Codeforces", "Twitter", "Reddit", "Medium"],
    "creative":  ["Behance", "Dribbble", "ArtStation", "Carbonmade", "Instagram", "Twitter", "Carrd"],
    "founder":   ["LinkedIn", "ProductHunt", "Gumroad", "Twitter", "Medium", "Substack", "HackerNews"],
    "exec":      ["LinkedIn", "Twitter", "Medium", "Substack"],
    "default":   ["LinkedIn", "GitHub", "Twitter", "Reddit", "Medium", "Instagram", "Keybase", "Gravatar"],
}


def curated(all_site_names, persona: str = "default") -> list[str]:
    """The GTM-valuable sites to enumerate for a persona, intersected with what we have data
    for. Falls back to every recognised GTM site if the persona is unknown."""
    want = PERSONA_ROUTES.get(persona) or list(GTM_SITES)
    have = set(all_site_names)
    return [s for s in want if s in have and s in GTM_SITES]
