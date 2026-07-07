"""PITH LEAD MINER — a Win98-flavored lead-gen + enrichment workbench over pith.

Two clicks to a list: pick a category + location, hit MINE. pith pulls real local businesses
from every configured source (OSM/Overpass + Overture keyless; Yelp/Google/Foursquare if you
add a free key) and waterfall-merges them — each row carries which sources agree (corroboration)
and a confidence score. Then ENRICH the rows you like: pith crawls each business's site for
emails/phones (contact evidence) and fingerprints its tech stack. Export the grid as CSV.

Run:  uv run --with streamlit --with overturemaps streamlit run examples/leadgen/app.py

The mining + enrichment logic is in plain functions (mine_leads / enrich_contacts / enrich_tech)
so it's testable without the UI — see tests/test_leadgen_app.py.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pith.leads import find_businesses, PROVIDERS, _CATEGORIES          # noqa: E402

# prefilled dropdowns (typeable — accept_new_options lets you enter anything not listed)
CATEGORY_OPTIONS = sorted(c.replace("_", " ") for c in _CATEGORIES)
LOCATION_OPTIONS = [
    "Phoenix, AZ", "Tucson, AZ", "Los Angeles, CA", "San Diego, CA", "San Francisco, CA",
    "Sacramento, CA", "Las Vegas, NV", "Denver, CO", "Dallas, TX", "Houston, TX", "Austin, TX",
    "San Antonio, TX", "Chicago, IL", "New York, NY", "Miami, FL", "Orlando, FL", "Tampa, FL",
    "Atlanta, GA", "Charlotte, NC", "Nashville, TN", "Seattle, WA", "Portland, OR", "Boston, MA",
    "Philadelphia, PA", "Columbus, OH", "Minneapolis, MN", "Kansas City, MO", "Tulsa, OK",
]


# ---------------------------------------------------------------------------
# engine (UI-free, testable)
# ---------------------------------------------------------------------------

LEAD_COLS = ["name", "confidence", "sources", "phone", "website", "address", "category",
             "email", "owner_email", "decision_maker", "title", "team", "rating", "hours",
             "linkedin", "socials", "extra_phones", "framework", "modernness", "enriched"]


def _flatten(biz: dict) -> dict:
    """A merged Business dict -> a flat grid row (enrichment columns start empty)."""
    return {
        "name": biz.get("name", ""),
        "confidence": round(biz.get("confidence", 0.0), 2),
        "sources": "+".join(biz.get("providers", [])),
        "phone": biz.get("phone", ""),
        "website": biz.get("website", ""),
        "address": biz.get("address", ""),
        "category": biz.get("category", ""),
        "email": "", "owner_email": "", "decision_maker": "", "title": "", "team": "",
        "rating": "", "hours": "", "linkedin": "", "socials": "", "extra_phones": "",
        "framework": "", "modernness": "", "enriched": "",
    }


def mine_leads(category: str, location: str, sources="auto", limit: int = 100,
               radius_km=None, has_website=False, has_phone=False, min_confidence=0.0,
               config=None) -> tuple[list[dict], dict]:
    """Pull + waterfall-merge leads. Returns (rows, coverage) — rows are flat grid dicts."""
    res = find_businesses(category, location, sources=sources, limit=limit, radius_km=radius_km,
                          has_website=has_website, has_phone=has_phone,
                          min_confidence=min_confidence, config=config or {})
    return [_flatten(b) for b in res["businesses"]], res["coverage"]


_SOCIAL_HOSTS = ("linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com")


def enrich_contacts(row: dict) -> dict:
    """Crawl the row's website and surface EVERYTHING pith pulls for free — not just an email.
    The site is the richest free source: role/owner email, extra phones, socials (incl. LinkedIn),
    and the decision-maker (schema.org Person + jobTitle). Returns column updates. No-op w/o site."""
    site = row.get("website")
    if not site:
        return {"enriched": "no site"}
    from pith.cli import contact_evidence
    from pith.recipes import owner_email, people, rank_phones
    if not site.startswith("http"):
        site = "https://" + site
    ev = contact_evidence(site, workers=6)          # one crawl -> contacts + people + firmographics + socials
    facts = ev["facts"]
    best = owner_email(facts)
    emails = [f.value for f in facts if f.kind == "email"]
    phones = [f.value for f in rank_phones(facts)]
    roster = people(facts)
    dm, title, dm_email = _pick_decision_maker(roster)
    socials = [f.value for f in facts if f.kind == "social" and any(h in f.value for h in _SOCIAL_HOSTS)]
    linkedin = next((s for s in socials if "linkedin.com" in s), "")
    fg = ev.get("firmographics", {})          # rating/hours from the crawl (no second fetch)
    rating = f"{fg['rating']}" + (f" ({fg['review_count']})" if fg.get("review_count") else "") if fg.get("rating") else ""
    return {
        "email": (best.value if best else "") or (emails[0] if emails else ""),
        "owner_email": (dm_email or (best.value if best else "")),
        "decision_maker": dm, "title": title,
        "team": " · ".join(f"{p['name']}" + (f" ({p['title'][:20]})" if p["title"] else "")
                            for p in roster[:4]),
        "rating": rating, "hours": fg.get("hours", ""),
        "linkedin": linkedin,
        "socials": ", ".join(socials)[:160],
        "extra_phones": ", ".join(p for p in phones if p != row.get("phone"))[:120],
        "enriched": "yes",
    }


_OWNERISH = ("owner", "founder", "president", "principal", "ceo", "partner", "proprietor")


def _pick_decision_maker(roster) -> tuple[str, str, str]:
    """From the people roster, pick the most decision-maker-ish: prefer an owner/founder/principal
    title, else the best-corroborated titled person. Returns (name, title, personal_email)."""
    if not roster:
        return "", "", ""
    ranked = sorted(roster, key=lambda p: (
        -any(o in (p["title"] or "").lower() for o in _OWNERISH),   # owner-ish first
        -bool(p["title"]), -p["corroboration"]))
    top = ranked[0]
    return top["name"], top["title"], (top["emails"][0] if top.get("emails") else "")


def enrich_tech(row: dict) -> dict:
    """Fingerprint the row's website (framework + modernness grade). Returns column updates."""
    site = row.get("website")
    if not site:
        return {"enriched": "no site"}
    from pith.cli import website_intel
    if not site.startswith("http"):
        site = "https://" + site
    intel = website_intel(site)
    return {
        "framework": intel.get("framework") or intel.get("builder") or "",
        "modernness": f"{intel.get('modernness_grade', '?')} ({intel.get('modernness_score', '?')})",
        "enriched": "yes",
    }


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

WIN98_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=VT323&display=swap');
:root{ --silver:#c0c0c0; --face:#c0c0c0; --hi:#ffffff; --sh:#808080; --dk:#000000; --navy:#000080; }
html, body, [class*="css"], .stApp{ font-family:"Tahoma","MS Sans Serif",sans-serif !important; font-size:12px !important; }
.stApp{ background:#008080 !important; }                                 /* teal desktop */
.block-container{ background:var(--silver); border:2px solid; border-color:var(--hi) var(--dk) var(--dk) var(--hi);
                  padding:0 !important; max-width:100% !important; box-shadow:2px 2px 0 #00000055; }
/* title bar */
.win-title{ background:linear-gradient(90deg,#000080,#1084d0); color:#fff; font-weight:bold; padding:3px 8px;
            display:flex; justify-content:space-between; align-items:center; letter-spacing:.5px; }
.win-title .btns span{ display:inline-block; width:16px; height:14px; background:var(--face); border:1px solid;
            border-color:var(--hi) var(--dk) var(--dk) var(--hi); text-align:center; line-height:12px; margin-left:2px; font-size:10px; color:#000; }
.win-body{ padding:10px 12px; }
.win-status{ background:var(--silver); border-top:1px solid var(--sh); padding:3px 8px; font-size:11px;
             display:flex; gap:14px; }
.win-status .cell{ border:1px solid; border-color:var(--sh) var(--hi) var(--hi) var(--sh); padding:1px 8px; }
/* beveled buttons */
.stButton>button, .stDownloadButton>button{ background:var(--face) !important; color:#000 !important; border-radius:0 !important;
            border:2px solid !important; border-color:var(--hi) var(--dk) var(--dk) var(--hi) !important; font-size:12px !important;
            padding:2px 14px !important; box-shadow:1px 1px 0 #00000033; font-family:inherit !important; }
.stButton>button:active{ border-color:var(--dk) var(--hi) var(--hi) var(--dk) !important; }
/* sunken inputs */
[data-baseweb="input"] input, [data-baseweb="select"]>div, .stTextInput input, .stNumberInput input{
            background:#fff !important; border-radius:0 !important; border:2px solid !important;
            border-color:var(--sh) var(--hi) var(--hi) var(--sh) !important; font-family:inherit !important; }
/* selectbox: the closed value AND the open dropdown menu — force dark text on white (baseweb
   renders the menu in a separate popover layer my input rule didn't reach). Role selectors are
   stable across baseweb versions. */
[data-baseweb="select"] *, [data-baseweb="select"] input{ color:#000 !important; }
[role="listbox"], [data-baseweb="popover"], [data-baseweb="menu"]{ background:#fff !important; }
[role="option"]{ color:#000 !important; background:#fff !important; font-family:inherit !important; }
[role="option"]:hover, [role="option"][aria-selected="true"]{ background:var(--navy) !important; color:#fff !important; }
section[data-testid="stSidebar"]{ background:var(--silver) !important; border-right:2px solid var(--dk); }
h1,h2,h3{ font-family:inherit !important; }
[data-testid="stDataFrame"]{ border:2px solid; border-color:var(--sh) var(--hi) var(--hi) var(--sh); }
</style>
"""


_LOG_STD = set(logging.LogRecord("n", 20, "p", 1, "m", (), None).__dict__) | {"message", "asctime", "taskName"}


class _BufHandler(logging.Handler):
    """Format each pith/scrapling log record into one firehose line (event + its extra fields)."""
    def __init__(self, buf):
        super().__init__()
        self.buf = buf

    def emit(self, r):
        try:
            extra = " ".join(f"{k}={v}" for k, v in r.__dict__.items()
                             if k not in _LOG_STD and not k.startswith("_"))
            self.buf.append(f"{r.name.split('.')[-1]:>10} · {r.getMessage()} {extra}".rstrip())
        except Exception:
            pass


def _run_streaming(label, fn):
    """Run fn() in a worker thread and firehose pith's backend logs (tier fetches, url_done,
    scrapling 'Fetched (200)', trafilatura) into a live panel while it works. Returns fn()'s value."""
    import threading
    import time
    from collections import deque

    import streamlit as st

    buf = deque(maxlen=500)
    h = _BufHandler(buf)
    h.setLevel(logging.DEBUG)
    levels = {"pith": logging.DEBUG, "scrapling": logging.INFO,
              "trafilatura": logging.INFO, "curl_cffi": logging.INFO}
    saved = [(logging.getLogger(n), logging.getLogger(n).level) for n in levels]
    for lg, _ in saved:
        lg.addHandler(h)
        lg.setLevel(levels[lg.name])
    out = {}

    def work():
        try:
            out["v"] = fn()
        except Exception as e:  # surface in the caller, not the worker thread
            out["e"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    with st.status(label, expanded=True) as status:
        panel = st.empty()
        while t.is_alive():
            panel.code("\n".join(list(buf)[-26:]) or "starting…", language="log")
            time.sleep(0.25)
        t.join()
        panel.code("\n".join(list(buf)[-26:]) or "(no backend logs)", language="log")
        status.update(state="error" if out.get("e") else "complete",
                      label=f"{label}  {'failed' if out.get('e') else 'done'}")
    for lg, lvl in saved:
        lg.removeHandler(h)
        lg.setLevel(lvl)
    if out.get("e"):
        raise out["e"]
    return out.get("v")


def _run_ui():
    import time

    import pandas as pd
    import streamlit as st

    st.set_page_config("PITH LEAD MINER", page_icon="🖥", layout="wide")
    st.markdown(WIN98_CSS, unsafe_allow_html=True)
    st.markdown('<div class="win-title"><span>▨ PITH LEAD MINER — [untitled.leads]</span>'
                '<span class="btns"><span>_</span><span>□</span><span>×</span></span></div>',
                unsafe_allow_html=True)

    ss = st.session_state
    ss.setdefault("rows", [])
    ss.setdefault("coverage", {})

    with st.sidebar:
        st.markdown("**⚙ Sources**")
        picked = [nm for nm, p in PROVIDERS.items()
                  if st.checkbox(f"{nm}{' (key)' if p.needs_key else ''}", value=not p.needs_key,
                                 help=p.reliability, key=f"src_{nm}")]
        st.markdown("**⧉ Filters**")
        limit = st.number_input("Max leads", 10, 500, 100, step=10)
        radius = st.number_input("Radius km (0 = whole city)", 0, 100, 0)
        only_site = st.checkbox("Has website")
        only_phone = st.checkbox("Has phone")
        min_conf = st.slider("Min confidence", 0.0, 1.0, 0.0, 0.05)

    st.markdown('<div class="win-body">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([3, 3, 1.4])
    category = c1.selectbox("Category", CATEGORY_OPTIONS, index=CATEGORY_OPTIONS.index("dentists"),
                            accept_new_options=True, label_visibility="collapsed",
                            placeholder="category (pick or type your own)")
    location = c2.selectbox("Location", LOCATION_OPTIONS, index=LOCATION_OPTIONS.index("Phoenix, AZ"),
                            accept_new_options=True, label_visibility="collapsed",
                            placeholder="city, ST (pick or type your own)")
    mine = c3.button("⛏ MINE", use_container_width=True)

    if mine:
        try:
            rows, cov = _run_streaming(
                f"⛏ Mining '{category}' in {location}…",
                lambda: mine_leads(category, location, sources=picked or "auto", limit=int(limit),
                                   radius_km=radius or None, has_website=only_site,
                                   has_phone=only_phone, min_confidence=min_conf))
            ss.rows, ss.coverage = rows, cov
            counts = " · ".join(f"{k}:{v}" for k, v in cov.get("counts", {}).items())
            st.caption(f"{len(rows)} leads  ({counts or 'no sources ran'})")
        except Exception as e:
            st.error(f"mine failed: {e}")

    if ss.rows:
        df = pd.DataFrame(ss.rows)[LEAD_COLS]
        n_site = sum(1 for r in ss.rows if r.get("website"))
        st.caption(f"{len(df)} leads · **{n_site} have a website** (enrichable) · select rows, then enrich. "
                   f"Tip: sort by the *website* column, or filter to sites, before enriching.")
        event = st.dataframe(df, use_container_width=True, height=430, hide_index=True,
                             on_select="rerun", selection_mode="multi-row",
                             column_config={
                                 "website": st.column_config.LinkColumn("website"),
                                 "confidence": st.column_config.ProgressColumn("conf", min_value=0, max_value=1, format="%.2f"),
                             })
        sel = event.selection.rows if event and event.selection else []
        b1, b2, b3, _ = st.columns([1.6, 1.6, 1.4, 4])
        do_contacts = b1.button(f"✉ Enrich contacts ({len(sel)})", disabled=not sel)
        do_tech = b2.button(f"🖧 Enrich tech ({len(sel)})", disabled=not sel)
        csv = df.to_csv(index=False).encode()
        b3.download_button("💾 Export CSV", csv, "leads.csv", "text/csv")

        if (do_contacts or do_tech) and sel:
            fn = enrich_contacts if do_contacts else enrich_tech
            log = logging.getLogger("pith")
            rows_ref = ss.rows        # plain list — bound here so the worker thread never touches session_state

            def _one(idx):
                r = rows_ref[idx]
                log.info("enrich_row", extra={"lead": r.get("name", "")[:34], "site": r.get("website", "")})
                try:
                    r.update(fn(r))
                except Exception as e:
                    r["framework" if do_tech else "email"] = f"err: {str(e)[:30]}"

            def _batch():                     # enrich leads concurrently (was one-at-a-time)
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=5) as pool:
                    list(pool.map(_one, sel))

            _run_streaming(f"{'✉ contacts' if do_contacts else '🖧 tech'} · enriching {len(sel)} leads (5 at a time)…", _batch)
            st.rerun()

        enriched = sum(1 for r in ss.rows if r.get("enriched") == "yes")
        st.markdown(f'<div class="win-status"><span class="cell">{len(ss.rows)} leads</span>'
                    f'<span class="cell">{enriched} enriched</span>'
                    f'<span class="cell">sources: {", ".join(ss.coverage.get("ran", [])) or "—"}</span>'
                    f'<span class="cell">Ready</span></div>', unsafe_allow_html=True)
    else:
        st.info("Pick a category + location and hit MINE. Add Yelp/Google/Foursquare keys in the "
                "environment to light up more sources (they merge + corroborate automatically).")
    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    _run_ui()
