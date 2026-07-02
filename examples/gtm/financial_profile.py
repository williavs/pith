"""A company's public financial profile — routed by what the company IS.

The core (pith.financials) exposes keyless sources each with a hard coverage boundary and a
one-call router (company_intel). This example is the JUDGMENT/framing layer: it reads the
bundle, picks the right story per company type, and — the point Willy wanted — is HONEST about
which companies this works for instead of faking a number:

  US PUBLIC   -> real SEC financials (annual, auditable) + live market cap + revenue percentile
  US PRIVATE  -> Reg D raise amounts (Form D) + Wikidata facts, no income statement (they file none)
  notable/non-US -> Wikidata + GLEIF identity
  small/local -> reported as "no public financial footprint" — not a blank

Run:  python examples/gtm/financial_profile.py "GitLab" GTLB     # public
      python examples/gtm/financial_profile.py "Databricks"      # private, big raises
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.financials import company_intel


def _usd(n):
    if n is None:
        return "—"
    n = float(n)
    return f"${n/1e9:.2f}B" if abs(n) >= 1e9 else f"${n/1e6:.1f}M" if abs(n) >= 1e6 else f"${n:,.0f}"


def _fin(v):
    return f"{_usd(v['value'])} ({v['period_end']} {v['form']})" if v else "—"


def render(b: dict) -> str:
    L = [f"FINANCIAL PROFILE: {b['company']}   [{b['kind']}]   sources: {', '.join(b['sources_used'])}"]
    if b["kind"] == "us_public":
        fin = (b.get("financials") or {}).get("financials", {})
        mkt, peer = b.get("market", {}), b.get("peer", {})
        L.append(f"  PUBLIC · {(b.get('financials') or {}).get('ticker')} · {(b.get('financials') or {}).get('industry')}")
        L.append(f"  revenue     {_fin(fin.get('revenue'))}"
                 + (f"   ({peer['percentile']}th pct of {peer['n_peers']} filers)" if peer.get('percentile') is not None else ""))
        L.append(f"  net income  {_fin(fin.get('net_income'))}")
        L.append(f"  assets      {_fin(fin.get('assets'))}    cash {_fin(fin.get('cash'))}")
        if mkt.get("found"):
            L.append(f"  market      {mkt['price']} {mkt['currency']} on {mkt['exchange']} (52wk {mkt.get('wk52_low')}-{mkt.get('wk52_high')})")
        fl = (b.get("filings") or {}).get("filings", [])
        if fl:
            L.append(f"  filings     {', '.join(f'{x['form']}·{x['date']}' for x in fl[:4])}")
    else:
        fund = (b.get("funding") or {}).get("raises", [])
        if fund:
            L.append("  PRIVATE · Reg D fundraising (Form D):")
            for r in fund[:4]:
                L.append(f"    {r.get('filed')}  raised {_usd(r.get('total_sold'))} of {_usd(r.get('total_offering'))}  ({r['entity'][:34]})")
        wf = (b.get("facts") or {}).get("facts", {})
        if wf:
            L.append(f"  facts       founded {str(wf.get('founded','?'))[:4]} · ~{wf.get('employees','?')} employees · {wf.get('industry','?')} · {wf.get('hq') or wf.get('headquarters','?')}")
        if not fund and not wf:
            L.append("  > no public financial footprint (small/local business, or no US filings / Wikidata entry)")
    idn = b.get("identity", {})
    if idn.get("found"):
        L.append(f"  identity    LEI {idn['lei']} · {idn.get('jurisdiction')} · {idn.get('status')}")
    return "\n".join(L)


if __name__ == "__main__":
    company = sys.argv[1] if len(sys.argv) > 1 else "GitLab"
    ticker = sys.argv[2] if len(sys.argv) > 2 else None
    print(render(company_intel(company, ticker)))
