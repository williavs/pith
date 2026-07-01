"""GTM value map for profile enumeration — which of the 482 vendored sites actually yield
firmographic (professional identity: role/company/industry) or psychographic (interests /
personality / behavior) data worth acting on. We enumerate THIS curated subset, not all 482
(the rest are gaming/forums/dating noise), and tag each result so a rep hits the right sites
for the right person. `recency` sites are where fresh activity = a buying-intent signal.

Refine empirically: run the enumerator on real people, see the actual output, adjust tags.
"""

# name (matches osint_sites.json key) -> (kind, value, recency_matters, what_you_get)
GTM_SITES = {
    # firmographic — who they are professionally
    "LinkedIn":    ("firmographic", "high", False, "role, company, tenure, education"),
    "GitHub":      ("firmographic", "high", True,  "technical role, employer in bio, projects, activity"),
    "Keybase":     ("firmographic", "high", False, "cryptographically-linked accounts — identity corroboration"),
    "Gravatar":    ("firmographic", "med",  False, "bio + linked profiles (aggregator)"),
    "AboutMe":     ("firmographic", "med",  False, "bio, role, curated links"),
    "GitLab":      ("firmographic", "med",  True,  "dev projects, employer"),
    "ProductHunt": ("firmographic", "med",  True,  "founder/maker, product launches"),
    "Behance":     ("firmographic", "med",  True,  "design portfolio (creative buyers)"),
    "Dribbble":    ("firmographic", "med",  True,  "design portfolio (creative buyers)"),
    # psychographic — how they think / what they care about
    "Twitter":     ("psychographic", "high", True,  "opinions, interests, engagement; recency = intent"),
    "Reddit":      ("psychographic", "high", True,  "unfiltered interests, pain points, questions asked"),
    "Medium":      ("psychographic", "high", True,  "thought-leadership topics they write about"),
    "Substack":    ("psychographic", "high", True,  "writing + subscriber interests"),
    "Instagram":   ("psychographic", "med",  True,  "lifestyle, personal interests"),
    "YouTube":     ("psychographic", "med",  True,  "content interests"),
    "Patreon":     ("psychographic", "low",  False, "causes/creators they support"),
}

# persona -> the sites that matter most for that buyer (right sites for the right people)
PERSONA_ROUTES = {
    "technical":  ["GitHub", "GitLab", "Twitter", "Reddit", "Medium"],       # CTO / dev / eng buyer
    "creative":   ["Behance", "Dribbble", "Instagram", "Twitter"],           # designer / agency
    "founder":    ["LinkedIn", "ProductHunt", "Twitter", "Medium", "Substack"],
    "exec":       ["LinkedIn", "Twitter", "Medium", "Substack"],
    "default":    ["LinkedIn", "GitHub", "Twitter", "Reddit", "Medium", "Instagram"],
}


def curated(all_site_names, persona: str = "default") -> list[str]:
    """The GTM-valuable sites to enumerate for a persona, intersected with what we have data
    for. Falls back to every GTM site if the persona is unknown."""
    want = PERSONA_ROUTES.get(persona) or list(GTM_SITES)
    have = set(all_site_names)
    return [s for s in want if s in have and s in GTM_SITES]
