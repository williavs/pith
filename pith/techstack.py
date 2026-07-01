"""Website tech + modernness intelligence — deterministic, from the page's HTML. For solo
founders selling website services: what's it built on, are they paying a DIY builder or
running something custom, is it mobile-responsive/secure/modern, and a letter grade so you
can filter a list down to the dated sites worth pitching.

No LLM. Signature-based (Wappalyzer-style) + a handful of high-signal modernness checks.
"""
from __future__ import annotations

import re

# (label, is_hosted_builder, signatures) — first match wins per group. Hosted builders mean
# the owner is PAYING a service (easy switch pitch); WordPress/custom is DIY-or-agency.
_BUILDERS = [
    ("Wix", True, ("wix.com", "wixstatic.com", "_wixcssstates", "x-wix")),
    ("Squarespace", True, ("squarespace.com", "static1.squarespace.com", "squarespace-cdn")),
    ("Shopify", True, ("cdn.shopify.com", "shopify.theme", "myshopify.com")),
    ("Webflow", True, ("webflow.io", "webflow.js", "assets-global.website-files.com")),
    ("GoDaddy Website Builder", True, ("img1.wsimg.com", "godaddy.com/websites", "websitebuilder")),
    ("Weebly", True, ("weebly.com", "editmysite.com")),
    ("Duda", True, ("dudaone", "duda_website", "dmsxml")),
    ("Square Online", True, ("squareup.com", "square-web")),
    # CMS content domains only — hs-scripts.com is just marketing tracking, not the builder
    ("HubSpot CMS", True, ("hubspotusercontent", "hs-sites.com")),
    ("WordPress", False, ("wp-content", "wp-json", "wp-includes")),
    ("Joomla", False, ("/media/jui/", "com_content", "joomla")),
    ("Drupal", False, ("sites/default/files", "drupal.js", "drupal-settings")),
]

_FRAMEWORKS = [
    ("Next.js", ("__next_data__", "/_next/")),
    ("Gatsby", ("___gatsby",)),
    ("Nuxt", ("__nuxt__", "/_nuxt/")),
    ("React", ("data-reactroot", "react-dom", "__react")),
    ("Vue", ("data-v-", "vue.js", "__vue__")),
    ("Angular", ("ng-version", "ng-app")),
    ("Svelte", ("svelte-",)),
]

# dated-tech signals (each is a real "this site is old" tell)
_DATED = [
    ("http-only", lambda h, u: u.startswith("http://")),
    ("table-layout", lambda h, u: len(re.findall(r"<table", h, re.I)) >= 3 and "grid-template" not in h and "flex" not in h.lower()),
    ("font-tag", lambda h, u: "<font" in h.lower()),
    ("flash", lambda h, u: "shockwave-flash" in h.lower() or ".swf" in h.lower()),
    ("old-jquery", lambda h, u: bool(re.search(r"jquery[/-]1\.\d", h, re.I))),
    ("frontpage", lambda h, u: "frontpage" in h.lower() or 'generator" content="microsoft' in h.lower()),
]


def _copyright_year(html):
    yrs = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)\s*\D{0,8}(20\d{2})", html, re.I)]
    return max(yrs) if yrs else None


def _first(pairs, html):
    low = html.lower()
    for label, *rest in pairs:
        sigs = rest[-1]
        if any(s in low for s in sigs):
            return label, rest
    return None, None


def analyze(html: str, url: str = "") -> dict:
    """HTML (+ url) -> tech + modernness intel. Deterministic."""
    html = html or ""
    builder, brest = _first(_BUILDERS, html)
    hosted = bool(brest and brest[0])
    framework, _ = _first([(f, None, s) for f, s in _FRAMEWORKS], html)
    responsive = 'viewport' in html.lower() and "width=device-width" in html.lower()
    https = url.startswith("https://")
    dated = [name for name, test in _DATED if test(html, url)]
    cyear = _copyright_year(html)

    modern_fw = framework in ("Next.js", "React", "Vue", "Gatsby", "Nuxt", "Svelte", "Angular")
    # letter grade: start at A, subtract for dated signals; modern framework helps.
    score = 100
    for name, pts in (("http-only", 12), ("table-layout", 15), ("font-tag", 10),
                      ("flash", 15), ("old-jquery", 10), ("frontpage", 12)):
        score -= pts if name in dated else 0
    score += 8 if modern_fw else 0
    if cyear and cyear <= 2018:
        score -= min(12, (2024 - cyear) * 2)
    # NOT mobile-responsive is the single strongest "needs a new site" tell — hard-cap the
    # grade so a non-responsive page can never read as modern, whatever else it has.
    if not responsive:
        score = min(score, 55)
        dated = dated + ["not-responsive"]
    score = max(0, min(100, score))
    grade = "A" if score >= 88 else "B" if score >= 76 else "C" if score >= 62 else "D" if score >= 48 else "F"

    return {
        "builder": builder or (f"custom ({framework})" if framework else "unknown"),
        "hosted_builder": hosted,          # True = paying a DIY service (switch-pitch)
        "framework": framework,
        "responsive": responsive,
        "https": https,
        "copyright_year": cyear,
        "dated_signals": dated,
        "modernness_grade": grade,
        "modernness_score": score,
    }
