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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pith.leads import find_businesses, PROVIDERS          # noqa: E402


# ---------------------------------------------------------------------------
# engine (UI-free, testable)
# ---------------------------------------------------------------------------

LEAD_COLS = ["name", "confidence", "sources", "phone", "website", "address", "category",
             "email", "extra_phones", "framework", "modernness", "enriched"]


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
        "email": "", "extra_phones": "", "framework": "", "modernness": "", "enriched": False,
    }


def mine_leads(category: str, location: str, sources="auto", limit: int = 100,
               radius_km=None, has_website=False, has_phone=False, min_confidence=0.0,
               config=None) -> tuple[list[dict], dict]:
    """Pull + waterfall-merge leads. Returns (rows, coverage) — rows are flat grid dicts."""
    res = find_businesses(category, location, sources=sources, limit=limit, radius_km=radius_km,
                          has_website=has_website, has_phone=has_phone,
                          min_confidence=min_confidence, config=config or {})
    return [_flatten(b) for b in res["businesses"]], res["coverage"]


def enrich_contacts(row: dict) -> dict:
    """Crawl the row's website for contact evidence; fill email + extra phones. Pure: returns a
    dict of column updates (or an 'error' key). No-op if the row has no website."""
    site = row.get("website")
    if not site:
        return {"error": "no website"}
    from pith.cli import contact_evidence
    from pith.recipes import owner_email, rank_phones
    if not site.startswith("http"):
        site = "https://" + site
    ev = contact_evidence(site, workers=4)
    facts = ev["facts"]
    best = owner_email(facts)
    phones = [f.value for f in rank_phones(facts)]
    return {
        "email": best or "",
        "extra_phones": ", ".join(p for p in phones if p != row.get("phone"))[:120],
        "enriched": True,
    }


def enrich_tech(row: dict) -> dict:
    """Fingerprint the row's website (framework + modernness grade). Returns column updates."""
    site = row.get("website")
    if not site:
        return {"error": "no website"}
    from pith.cli import website_intel
    if not site.startswith("http"):
        site = "https://" + site
    intel = website_intel(site)
    return {
        "framework": intel.get("framework") or intel.get("builder") or "",
        "modernness": f"{intel.get('modernness_grade', '?')} ({intel.get('modernness_score', '?')})",
        "enriched": True,
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
section[data-testid="stSidebar"]{ background:var(--silver) !important; border-right:2px solid var(--dk); }
h1,h2,h3{ font-family:inherit !important; }
[data-testid="stDataFrame"]{ border:2px solid; border-color:var(--sh) var(--hi) var(--hi) var(--sh); }
</style>
"""


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
    category = c1.text_input("Category", "dentists", label_visibility="collapsed", placeholder="category e.g. dentists")
    location = c2.text_input("Location", "Phoenix, AZ", label_visibility="collapsed", placeholder="city, ST")
    mine = c3.button("⛏ MINE", use_container_width=True)

    if mine:
        with st.status(f"Mining '{category}' in {location}…", expanded=True) as status:
            try:
                rows, cov = mine_leads(category, location, sources=picked or "auto", limit=int(limit),
                                       radius_km=radius or None, has_website=only_site,
                                       has_phone=only_phone, min_confidence=min_conf)
                ss.rows, ss.coverage = rows, cov
                counts = " · ".join(f"{k}:{v}" for k, v in cov.get("counts", {}).items())
                status.update(label=f"{len(rows)} leads  ({counts or 'no sources ran'})", state="complete")
            except Exception as e:
                status.update(label=f"mine failed: {e}", state="error")

    if ss.rows:
        df = pd.DataFrame(ss.rows)[LEAD_COLS]
        st.caption(f"{len(df)} leads · select rows, then enrich")
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
            prog = st.progress(0.0, "enriching…")
            for i, idx in enumerate(sel):
                try:
                    ss.rows[idx].update(fn(ss.rows[idx]))
                except Exception as e:
                    ss.rows[idx]["framework" if do_tech else "email"] = f"err: {str(e)[:30]}"
                prog.progress((i + 1) / len(sel), f"enriched {i + 1}/{len(sel)}")
            st.rerun()

        enriched = sum(1 for r in ss.rows if r.get("enriched"))
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
