"""List Cleaner dashboard — visualize + slice a cleaned contact list without choking on 73k rows.

Streamlit can't render (or edit) a 73k-row grid, so it doesn't try: this loads the cleaned CSV
(produced by clean.py), shows SUMMARY metrics + charts over the full set, lets you FILTER to the
segment you'd actually sell to, previews a capped sample of that segment, and downloads the FULL
filtered set. Aggregates + a small preview + a download link — full data quality, no UI meltdown.

Run:  uv run --with streamlit --with pandas streamlit run examples/list-cleaner/dashboard.py
  (point it at the cleaned.csv from: python examples/list-cleaner/clean.py <list.xlsx>)
"""
import os

import pandas as pd
import streamlit as st

st.set_page_config("pith · list cleaner", page_icon="🧹", layout="wide")
PREVIEW_CAP = 500


@st.cache_data(show_spinner="loading cleaned list…")
def load(path):
    return pd.read_csv(os.path.expanduser(path), dtype={"sanitized_phone": str, "phone_e164": str})


st.title("🧹 List Cleaner")
st.caption("Validate + segment a stale contact list. Full data on disk; this shows summaries, a "
           "capped preview, and a filtered download — Streamlit never renders all the rows.")

path = st.text_input("Cleaned CSV path", "~/Downloads/business_owners_cleaned.csv",
                     help="Output of clean.py. Run that first if you haven't.")
if not os.path.exists(os.path.expanduser(path)):
    st.info("Run the cleaner first:\n\n"
            "`uv run --with pandas --with openpyxl --with dnspython python examples/list-cleaner/clean.py "
            "\"<your list>.xlsx\" -o ~/Downloads/business_owners_cleaned.csv`")
    st.stop()

df = load(path)
n = len(df)

# ---- top-line metrics (over the full set) ----
q = df["quality"].value_counts()
c = st.columns(5)
c[0].metric("Rows", f"{n:,}")
c[1].metric("Sellable", f"{q.get('sellable', 0):,}", f"{100*q.get('sellable',0)//n}%")
c[2].metric("Risky", f"{q.get('risky', 0):,}")
c[3].metric("Dead", f"{q.get('dead', 0):,}")
if "phone_valid" in df:
    c[4].metric("Valid phones", f"{int(df['phone_valid'].sum()):,}", f"{100*int(df['phone_valid'].sum())//n}%")

# ---- charts (full set) ----
a, b = st.columns(2)
with a:
    st.markdown("**Quality**")
    st.bar_chart(q)
with b:
    if "phone_line_type" in df.columns:
        st.markdown("**Phone line types (valid only)**")
        lt = df.loc[df["phone_valid"] == True, "phone_line_type"].value_counts()  # noqa: E712
        st.bar_chart(lt)

with st.expander("Top email domains"):
    st.bar_chart(df["email_domain"].value_counts().head(15))

# ---- filters -> the segment you'd sell ----
st.sidebar.header("Filter the segment")
qs = st.sidebar.multiselect("Quality", ["sellable", "risky", "dead"], default=["sellable"])
need_phone = st.sidebar.checkbox("Has valid phone", value=False)
no_free = st.sidebar.checkbox("Exclude freemail (gmail/…)", value=False)
no_role = st.sidebar.checkbox("Exclude role inboxes (info@/…)", value=False)
no_dupe = st.sidebar.checkbox("Drop duplicate emails", value=True)
regions = sorted(str(x) for x in df.get("phone_region", pd.Series()).dropna().unique() if x)
pick_regions = st.sidebar.multiselect("Phone region", regions)

f = df["quality"].isin(qs)
if need_phone and "phone_valid" in df:
    f &= df["phone_valid"] == True  # noqa: E712
if no_free:
    f &= ~df["is_freemail"].fillna(False)
if no_role:
    f &= ~df["is_role"].fillna(False)
if no_dupe and "is_duplicate_email" in df:
    f &= ~df["is_duplicate_email"].fillna(False)
if pick_regions:
    f &= df["phone_region"].isin(pick_regions)
fdf = df[f]

st.subheader(f"Segment: {len(fdf):,} contacts  ({100*len(fdf)//n if n else 0}% of list)")
st.download_button(f"⤓ Download this segment ({len(fdf):,} rows)",
                   fdf.to_csv(index=False).encode(), "segment.csv", "text/csv")
st.caption(f"Preview (first {PREVIEW_CAP} of {len(fdf):,}) — the full segment is in the download.")
cols = [c for c in ["name", "title", "organization_name", "email", "quality", "has_mx",
                    "phone_e164", "phone_region", "phone_line_type", "linkedin_url"] if c in fdf.columns]
st.dataframe(fdf[cols].head(PREVIEW_CAP), use_container_width=True, height=460, hide_index=True,
             column_config={"linkedin_url": st.column_config.LinkColumn("linkedin")})
