"""PITH ACCOUNT INTELLIGENCE — B2B account enrichment over the full pith stack.

Different game from local lead-gen. Here you bring target-account DOMAINS (or discover recently-
funded companies via SEC Form D) and pith assembles the signals a B2B seller actually needs:

  firmographics  name / domain / industry / employees / founded / HQ   (Wikidata)
  funding        latest raise (Form D) or public financials            (pith.financials)
  hiring         open roles + which departments + ATS                  (pith.jobs)  <- growth signal
  tech           stack + modernness                                    (pith.cli.website_intel)
  signals        tagged news counts (funding/leadership/product/ai/…)  (pith.news)  <- why-reach-out-now
  contact        email / phone                                         (pith.cli.contact_evidence)
  people         best-effort decision-makers (exec-titled)             (pith.people)

A LENS reorders what matters: selling PAYROLL cares about headcount + hiring velocity + funding;
selling AI SERVICES cares about tech + eng/AI hiring + product news. Same dossier, different read.

Honest boundaries: website people extraction is reliable on small cos, noisy on big ones (surfaced
best-effort). Firmographics need a Wikidata entry. The reliable B2B value is hiring + news + tech +
funding — those work on any company with a domain.

Run:  uv run --with streamlit streamlit run examples/b2b/app.py

Engine functions (enrich_account) are UI-free and tested in tests/test_b2b_app.py.
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ACCOUNT_COLS = ["name", "domain", "industry", "employees", "founded", "hq",
                "funding", "open_roles", "top_depts", "ats", "tech", "modernness",
                "signals", "email", "phone", "lens_read", "enriched"]

# NOTE: no decision-maker column here — measured on real B2B accounts, free website extraction of
# execs is garbage on large companies (blog authors / customer logos / advisors pollute the crawl
# and survive corroboration). B2B decision-makers are LinkedIn/paid-B2B territory. Website people
# extraction IS reliable on small local businesses — see the leadgen app, which keeps that column.


def _parse_target(line: str) -> tuple[str, str]:
    """'domain' | 'Name,domain' | 'https://domain' -> (name, domain). Name derived from the
    domain's second-level label when not given."""
    line = line.strip()
    name = ""
    if "," in line:
        a, b = [x.strip() for x in line.split(",", 1)]
        if "." in b:
            name, line = a, b
        elif "." in a:
            name, line = b, a
    host = urlsplit(line if "//" in line else "//" + line).netloc or line
    domain = host.lower().lstrip("www.").strip("/")
    if not name:
        sld = domain.split(".")[0] if "." in domain else domain
        name = sld.replace("-", " ").title()
    return name, domain


def _news_signals(items) -> str:
    tags: dict[str, int] = {}
    for it in items:
        s = it.get("signal")
        if s and s != "news":
            tags[s] = tags.get(s, 0) + 1
    return " ".join(f"{k}:{v}" for k, v in sorted(tags.items(), key=lambda x: -x[1]))


def _lens_read(d: dict, lens: str) -> str:
    """Surface the lens-relevant EVIDENCE (not a score) — the seller judges fit."""
    if lens == "payroll":
        bits = [f"~{d['employees']} employees" if d["employees"] else "",
                f"{d['open_roles']} open roles" if d["open_roles"] else "",
                f"funding: {d['funding']}" if d["funding"] else ""]
    elif lens == "ai_services":
        ai = re.search(r"ai:(\d+)", d["signals"] or "")
        bits = [f"tech: {d['tech']}" if d["tech"] else "",
                f"{d['open_roles']} open roles" if d["open_roles"] else "",
                f"ai news: {ai.group(1)}" if ai else "",
                f"funding: {d['funding']}" if d["funding"] else ""]
    else:
        bits = [f"{d['open_roles']} roles" if d["open_roles"] else "",
                d["signals"] or "", f"funding: {d['funding']}" if d["funding"] else ""]
    return " · ".join(b for b in bits if b)


def enrich_account(target: str, lens: str = "generic") -> dict:
    """One target (domain | 'Name,domain') -> a B2B dossier row. Every pith call is guarded so a
    single source failing never sinks the account."""
    from pith.cli import contact_evidence, website_intel
    from pith.financials import company_intel
    from pith.jobs import jobs_search
    from pith.news import news_search
    from pith.recipes import owner_email, rank_phones

    name, domain = _parse_target(target)
    d = {c: "" for c in ACCOUNT_COLS}
    d.update({"name": name, "domain": domain, "open_roles": 0, "enriched": True})
    url = "https://" + domain

    try:
        wi = website_intel(url)
        d["tech"] = wi.get("framework") or wi.get("builder") or ""
        d["modernness"] = wi.get("modernness_grade") or ""
    except Exception:
        pass
    try:
        j = jobs_search(name, domain)
        d["open_roles"], d["ats"] = j.get("count", 0), j.get("ats") or ""
        depts: dict[str, int] = {}
        for p in j.get("postings", []):
            k = p.get("department") or "?"
            depts[k] = depts.get(k, 0) + 1
        d["top_depts"] = ", ".join(f"{k}({v})" for k, v in sorted(depts.items(), key=lambda x: -x[1])[:3] if k != "?")
    except Exception:
        pass
    try:
        d["signals"] = _news_signals(news_search(name, domain=domain, window_days=120))
    except Exception:
        pass
    try:
        ci = company_intel(name)
        d["industry"] = ((ci.get("facts") or {}).get("facts") or {}).get("industry", "") or \
            ((ci.get("financials") or {}).get("industry", "") if ci.get("financials") else "")
        wf = (ci.get("facts") or {}).get("facts") or {}
        d["employees"] = wf.get("employees", "") or ""
        d["founded"] = str(wf.get("founded", ""))[:4] if wf.get("founded") else ""
        d["hq"] = wf.get("hq") or wf.get("headquarters", "") or ""
        d["funding"] = _funding_str(ci)
    except Exception:
        pass
    try:
        ev = contact_evidence(url, workers=6)
        facts = ev["facts"]
        be = owner_email(facts)
        emails = [f.value for f in facts if f.kind == "email"]
        phones = [f.value for f in rank_phones(facts)]
        d["email"] = (be.value if be else "") or (emails[0] if emails else "")
        d["phone"] = phones[0] if phones else ""
    except Exception:
        pass

    d["lens_read"] = _lens_read(d, lens)
    return d


def _funding_str(ci: dict) -> str:
    if ci.get("kind") == "us_public":
        fin = (ci.get("financials") or {}).get("financials") or {}
        rev = fin.get("revenue")
        return f"public · rev {_usd(rev['value'])}" if rev else "public"
    raises = (ci.get("funding") or {}).get("raises") or []
    if raises:
        r = max(raises, key=lambda x: float(x.get("total_sold") or 0))   # largest, not oldest
        return f"raised {_usd(r.get('total_sold'))} ({r.get('filed', '')[:7]})"
    return ""


def _usd(n):
    if not n:
        return "—"
    n = float(n)
    return f"${n/1e9:.1f}B" if n >= 1e9 else f"${n/1e6:.0f}M" if n >= 1e6 else f"${n:,.0f}"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;600;700&display=swap');
.stApp{ background:#0e1116; }
html,body,[class*="css"]{ font-family:'IBM Plex Sans',sans-serif; }
.hdr{ font-family:'IBM Plex Mono',monospace; color:#3ddc84; font-weight:600; font-size:22px;
      border-bottom:1px solid #263140; padding:10px 0 12px; letter-spacing:1px; }
.hdr small{ color:#6b7a8d; font-weight:400; letter-spacing:0; }
.stButton>button{ background:#16202c; color:#3ddc84; border:1px solid #2b6b46; border-radius:3px;
      font-family:'IBM Plex Mono',monospace; font-weight:600; }
.stButton>button:hover{ background:#1c2a38; border-color:#3ddc84; }
[data-testid="stDataFrame"]{ border:1px solid #263140; }
label,.stMarkdown,p{ color:#c3cdd9; }
h1,h2,h3{ color:#e6edf3; font-family:'IBM Plex Mono',monospace; }
</style>
"""


def _run_ui():
    import pandas as pd
    import streamlit as st

    st.set_page_config("pith · account intelligence", page_icon="◈", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="hdr">◈ PITH ACCOUNT INTELLIGENCE &nbsp;<small>// B2B signal dossier</small></div>',
                unsafe_allow_html=True)

    ss = st.session_state
    ss.setdefault("rows", [])

    with st.sidebar:
        st.markdown("**LENS** — what you're selling")
        lens = st.radio("lens", ["generic", "payroll", "ai_services"], label_visibility="collapsed",
                        help="payroll: headcount + hiring + funding · ai_services: tech + eng hiring + AI news")
        st.caption("Paste target-account domains (or `Name,domain`), one per line.")

    targets = st.text_area("Target accounts", "ramp.com\nvercel.com\nnotion.so",
                           height=130, label_visibility="collapsed")
    if st.button("▸ ENRICH ACCOUNTS"):
        lines = [ln for ln in targets.splitlines() if ln.strip()]
        rows, prog = [], st.progress(0.0, "enriching…")
        for i, ln in enumerate(lines):
            try:
                rows.append(enrich_account(ln, lens=lens))
            except Exception as e:
                rows.append({**{c: "" for c in ACCOUNT_COLS}, "name": ln, "lens_read": f"error: {e}"})
            prog.progress((i + 1) / len(lines), f"{i+1}/{len(lines)}")
        ss.rows = rows

    if ss.rows:
        # re-read the lens column without re-fetching
        for r in ss.rows:
            r["lens_read"] = _lens_read(r, lens)
        df = pd.DataFrame(ss.rows)[ACCOUNT_COLS]
        st.dataframe(df, use_container_width=True, height=460, hide_index=True,
                     column_config={"domain": st.column_config.TextColumn(),
                                    "lens_read": st.column_config.TextColumn(f"read · {lens}", width="large")})
        st.download_button("⤓ Export CSV", df.to_csv(index=False).encode(), "accounts.csv", "text/csv")
    else:
        st.info("Paste domains and hit ENRICH. The reliable B2B signals — hiring, news, tech, "
                "funding — work on any company with a domain. Firmographics need a Wikidata entry. "
                "Decision-makers aren't here: on large companies free website extraction is noise "
                "(LinkedIn/paid-B2B territory) — find the person there once these signals qualify the account.")


if __name__ == "__main__":
    _run_ui()
