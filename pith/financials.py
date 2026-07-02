"""Keyless public financial + funding + identity data — cleaned, structured, no key, no LLM.

Grounded in the official docs (SEC EDGAR APIs, GLEIF, Wikidata) and verified live. Every
number is auditable back to a filing/record. COVERAGE IS FRAMED per function — pith tells you
when a company is out of scope instead of returning a silent blank:

  sec_financials / peer_percentile  -> US SEC-reporting PUBLIC cos + SEC-registered foreign
        issuers that tag XBRL (10-K/10-Q, 20-F, ~2009+). NOT US-private (Stripe/OpenAI = no CIK).
  sec_filings                       -> anything that ever filed with EDGAR (8-K/10-K/S-1/Form D...).
  sec_ownership                     -> US public only — insider Form 4 (an exec BUYING = conviction).
  form_d_raises                     -> US private cos that filed a Reg D (real raise $) — most
        VC-backed startups; noisy for names shared with SPVs (OpenAI-type), scoped by exact name.
  company_facts                     -> NOTABLE cos (public/private/non-US) with a Wikidata entry.
  registry_identity                 -> ANY entity with a GLEIF LEI (global identity + parent/child; no financials).
  market_quote                      -> US/major-exchange public tickers (live price, market cap).
  company_intel                     -> the one-call bundle: routes to only the sources that apply.

Small/local businesses have no public financial footprint — that is reported, not faked. SEC
asks for a UA identifying you (name email) and caps at 10 req/s; set PITH_SEC_UA.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from bisect import bisect_left
from datetime import date

_SEC_UA = os.environ.get("PITH_SEC_UA", "pith-osint-lib admin@pith.dev")   # SEC wants "name email"
_TICKERS = None
_lock = threading.Lock()
_last = [0.0]


def _get(url, ua=None, timeout=15):
    from .core import _guard_url
    _guard_url(url)
    with _lock:                                    # polite global throttle (SEC hard cap 10 req/s)
        wait = 0.11 - (time.monotonic() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": ua or _SEC_UA, "Accept-Encoding": "gzip, deflate"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            data = gzip.decompress(data)
    return data.decode("utf-8", "ignore")


def _jget(url, ua=None):
    return json.loads(_get(url, ua=ua))


# ---------------- SEC (US public) ----------------

def _ticker_map():
    global _TICKERS
    if _TICKERS is None:
        _TICKERS = list(_jget("https://www.sec.gov/files/company_tickers.json").values())
    return _TICKERS


def _resolve_cik(company, ticker=None):
    m = _ticker_map()
    if ticker:
        hit = next((c for c in m if c["ticker"].lower() == ticker.lower()), None)
    else:
        q = (company or "").strip().lower()
        hit = (next((c for c in m if c["ticker"].lower() == q), None)
               or next((c for c in m if c["title"].lower() == q), None)
               or next((c for c in m if q and q in c["title"].lower()), None))
    return (str(hit["cik_str"]).zfill(10), hit["ticker"], hit["title"]) if hit else None


# metric -> (xbrl concept candidates, is instantaneous/balance-sheet)
_METRICS = {
    "revenue": (["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"], False),
    "net_income": (["NetIncomeLoss"], False),
    "gross_profit": (["GrossProfit"], False),
    "operating_income": (["OperatingIncomeLoss"], False),
    "rd_expense": (["ResearchAndDevelopmentExpense"], False),
    "assets": (["Assets"], True),
    "liabilities": (["Liabilities"], True),
    "equity": (["StockholdersEquity"], True),
    "cash": (["CashAndCashEquivalentsAtCarryingValue"], True),
}
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def _days(a, b):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return 0


def _latest(gaap, candidates, instantaneous):
    """The latest ANNUAL value — period-aware (a 10-K duration of ~1yr, not a 10-Q quarter).
    The naive 'max by end date' grabs a quarterly figure; this fixes it."""
    for c in candidates:
        units = (gaap.get(c) or {}).get("units", {}).get("USD")
        if not units:
            continue
        if instantaneous:
            facts = [u for u in units if u.get("form") in _ANNUAL_FORMS]
        else:
            facts = [u for u in units if u.get("form") in _ANNUAL_FORMS and u.get("start") and 300 <= _days(u["start"], u["end"]) <= 400]
        facts = facts or units                     # fallback: whatever exists
        best = max(facts, key=lambda u: (u.get("end", ""), u.get("filed", "")))
        return {"value": best["val"], "period_end": best.get("end"), "fiscal_year": best.get("fy"),
                "form": best.get("form"), "filed": best.get("filed"), "accession": best.get("accn")}
    return None


def sec_financials(company: str, ticker: str | None = None) -> dict:
    out = {"company": company, "applies_to": "US SEC-reporting public companies (XBRL filers)", "is_public": False}
    r = _resolve_cik(company, ticker)
    if not r:
        out["note"] = "not a US public filer — try company_facts()/registry_identity() or form_d_raises()"
        return out
    cik, tk, name = r
    out.update(is_public=True, cik=cik, ticker=tk, name=name)
    try:
        sub = _jget(f"https://data.sec.gov/submissions/CIK{cik}.json")
        out["industry"] = sub.get("sicDescription")
        rec, ci = sub["filings"]["recent"], int(cik)
        out["recent_filings"] = [
            {"form": rec["form"][i], "date": rec["filingDate"][i], "signal": _FORM_SIGNAL.get(rec["form"][i], "filing"),
             "url": f"https://www.sec.gov/Archives/edgar/data/{ci}/{rec['accessionNumber'][i].replace('-', '')}/{rec['primaryDocument'][i]}"}
            for i in range(min(10, len(rec["form"])))]
    except Exception as e:
        out["filings_error"] = str(e)[:80]
    try:
        gaap = _jget(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").get("facts", {}).get("us-gaap", {})
        out["financials"] = {k: _latest(gaap, cands, inst) for k, (cands, inst) in _METRICS.items()}
    except Exception as e:
        out["financials_error"] = str(e)[:80]
    return out


_FORM_SIGNAL = {"8-K": "material_event", "10-K": "annual_report", "10-Q": "quarterly_report",
                "S-1": "ipo_registration", "4": "insider_trade", "SC 13D": "activist_stake",
                "SC 13G": "passive_stake", "DEF 14A": "proxy_exec_comp", "424B4": "ipo_pricing"}


def sec_filings(company: str = "", ticker: str | None = None, forms: list[str] | None = None, limit: int = 20) -> dict:
    """CIK-scoped filings (reliable — avoids the full-text 'Stripe Milton LLC' name-noise trap)."""
    out = {"company": company, "applies_to": "any entity that has filed with SEC EDGAR"}
    r = _resolve_cik(company, ticker)
    if not r:
        out["note"] = "no CIK for this name (private/non-filer). Use form_d_raises() for private raises."
        return out
    cik, tk, name = r
    out.update(cik=cik, ticker=tk, name=name)
    try:
        rec, ci = _jget(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"], int(cik)
        rows = []
        for i in range(len(rec["form"])):
            if forms and rec["form"][i] not in forms:
                continue
            rows.append({"form": rec["form"][i], "date": rec["filingDate"][i],
                         "signal": _FORM_SIGNAL.get(rec["form"][i], "filing"),
                         "url": f"https://www.sec.gov/Archives/edgar/data/{ci}/{rec['accessionNumber'][i].replace('-', '')}/{rec['primaryDocument'][i]}"})
            if len(rows) >= limit:
                break
        out["count"], out["filings"] = len(rows), rows
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def sec_ownership(company: str, ticker: str | None = None, limit: int = 15) -> dict:
    """Insider (Form 4) transactions — an officer/director BUYING (code P) is a conviction signal.
    US public only."""
    out = {"company": company, "applies_to": "US public companies (Section 16 insiders)"}
    r = _resolve_cik(company, ticker)
    if not r:
        out["note"] = "US public companies only"
        return out
    cik, tk, name = r
    out.update(cik=cik, ticker=tk)
    try:
        rec, ci = _jget(f"https://data.sec.gov/submissions/CIK{cik}.json")["filings"]["recent"], int(cik)
        txns = []
        for i in range(len(rec["form"])):
            if len(txns) >= limit:
                break
            if rec["form"][i] != "4":
                continue
            acc = rec["accessionNumber"][i].replace("-", "")
            txns.append({"date": rec["filingDate"][i], "accession": rec["accessionNumber"][i],
                         "url": f"https://www.sec.gov/Archives/edgar/data/{ci}/{acc}/{rec['primaryDocument'][i]}"})
        out["count"], out["form4_filings"] = len(txns), txns
        out["note"] = "recent insider (Form 4) filings; the buy/sell code + shares + price are in each filing's XML"
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


def peer_percentile(company: str, metric: str = "revenue", ticker: str | None = None, year: int | None = None) -> dict:
    """Where a company's metric ranks vs ALL XBRL filers for a period (SEC frames API)."""
    out = {"company": company, "metric": metric, "applies_to": "US public XBRL filers"}
    r = _resolve_cik(company, ticker)
    if not r or metric not in _METRICS:
        out["note"] = "US public company + a supported metric required"
        return out
    cik, tk, name = r
    cands, inst = _METRICS[metric]
    yr = year or (date.today().year - 1)
    for concept in cands:
        try:
            frame = _jget(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{yr}{'I' if inst else ''}.json")
            data = frame.get("data", [])
            mine = next((d for d in data if str(d["cik"]).zfill(10) == cik), None)
            if not mine:
                continue
            vals = sorted(d["val"] for d in data)
            pct = round(100 * bisect_left(vals, mine["val"]) / len(vals), 1)
            out.update(value=mine["val"], period=f"CY{yr}", percentile=pct, n_peers=len(data), concept=concept)
            return out
        except Exception:
            continue
    out["note"] = f"no CY{yr} frame value for {company} (off-calendar fiscal year or not tagged)"
    return out


def form_d_raises(company: str, limit: int = 8) -> dict:
    """US private Reg D fundraising with the REAL raise amount (two-hop: full-text -> primary_doc.xml).
    Noisy for names shared with SPVs — filter to filings whose entity name matches the company."""
    out = {"company": company, "applies_to": "US private companies that filed a Reg D (Form D)"}
    try:
        q = urllib.parse.quote(f'"{company}"')
        h = (_jget(f"https://efts.sec.gov/LATEST/search-index?q={q}&forms=D").get("hits") or {})
        hits = h.get("hits") or []
        out["count"] = (h.get("total") or {}).get("value", len(hits))
        want = set(re.sub(r"[^a-z0-9 ]", "", company.lower()).split())
        raises = []
        for hit in hits[:limit * 2]:
            src = hit.get("_source", {})
            entity = (src.get("display_names") or [""])[0]
            if want and not (want & set(re.sub(r"[^a-z0-9 ]", "", entity.lower()).split())):
                continue                           # skip SPV/fund name collisions
            acc_id = hit["_id"].split(":")[0]      # e.g. 0001587468-25-000008
            cik = int(acc_id.split("-")[0])        # filer CIK = accession's leading segment (efts cik is null)
            acc = acc_id.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"
            amt = {}
            try:
                xml = _get(url)
                sold = re.search(r"<totalAmountSold>\s*([\d.]+)", xml)
                offer = re.search(r"<totalOfferingAmount>\s*([\d.]+)", xml)
                amt = {"total_sold": int(float(sold.group(1))) if sold else None,
                       "total_offering": int(float(offer.group(1))) if offer else None}
            except Exception:
                pass
            raises.append({"entity": entity, "cik": cik, "filed": src.get("file_date"), **amt, "url": url})
            if len(raises) >= limit:
                break
        out["raises"] = raises
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


# ---------------- Wikidata (notable, any type) ----------------

_WD_UA = "pith-osint (admin@pith.dev)"
_WD_PROPS = {"P571": "founded", "P1128": "employees", "P2139": "revenue", "P159": "headquarters",
             "P452": "industry", "P856": "website", "P169": "ceo", "P749": "parent", "P414": "stock_exchange"}


def company_facts(company: str) -> dict:
    out = {"company": company, "applies_to": "notable companies (public/private/non-US) with a Wikidata entry", "found": False}
    try:
        s = _jget("https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&limit=6"
                  f"&language=en&format=json&search={urllib.parse.quote(company)}", ua=_WD_UA)
        qid = None
        for hit in s.get("search", []):
            d = (hit.get("description") or "").lower()
            if any(w in d for w in ("company", "business", "corporation", "enterprise", "startup",
                                    "brand", "manufacturer", "bank", "firm", "platform", "service")):
                qid = hit["id"]
                break
        qid = qid or (s["search"][0]["id"] if s.get("search") else None)
        if not qid:
            return out
        claims = _jget(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json", ua=_WD_UA)["entities"][qid].get("claims", {})
        facts, refs = {}, {}
        for pid, nm in _WD_PROPS.items():
            if pid not in claims:
                continue
            v = claims[pid][0].get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(v, dict) and "amount" in v:
                facts[nm] = v["amount"].lstrip("+")
            elif isinstance(v, dict) and "time" in v:
                facts[nm] = v["time"].lstrip("+")[:10]
            elif isinstance(v, dict) and v.get("id"):
                refs[nm] = v["id"]
            elif v is not None:
                facts[nm] = v
        if refs:
            lab = _jget(f"https://www.wikidata.org/w/api.php?action=wbgetentities&ids={'|'.join(refs.values())}"
                        "&props=labels&languages=en&format=json", ua=_WD_UA)["entities"]
            for nm, rid in refs.items():
                facts[nm] = lab.get(rid, {}).get("labels", {}).get("en", {}).get("value", rid)
        out.update(found=True, qid=qid, facts=facts)
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


# ---------------- GLEIF (global identity) ----------------

def registry_identity(company: str, lei: str | None = None) -> dict:
    out = {"company": company, "applies_to": "any legal entity with a GLEIF LEI (global; identity + hierarchy, no financials)", "found": False}
    try:
        if lei:
            rec = _jget(f"https://api.gleif.org/api/v1/lei-records/{lei}", ua="pith-osint")["data"]
        else:
            recs = _jget("https://api.gleif.org/api/v1/lei-records?page[size]=1&filter[entity.legalName]="
                         + urllib.parse.quote(company), ua="pith-osint").get("data", [])
            if not recs:
                out["note"] = "no LEI match (many small/US-only cos lack an LEI)"
                return out
            rec = recs[0]
        a = rec["attributes"]
        e = a["entity"]
        out.update(found=True, lei=a["lei"], legal_name=e["legalName"]["name"],
                   jurisdiction=e.get("jurisdiction"), legal_form=(e.get("legalForm") or {}).get("id"),
                   status=e.get("status"),
                   country=(e.get("legalAddress") or {}).get("country"),
                   hq_country=(e.get("headquartersAddress") or {}).get("country"))
    except Exception as ex:
        out["error"] = str(ex)[:80]
    return out


# ---------------- market quote (Yahoo, keyless) ----------------

def market_quote(ticker: str) -> dict:
    out = {"ticker": ticker, "applies_to": "US/major-exchange public tickers", "found": False}
    try:
        m = _jget(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}", ua="Mozilla/5.0")["chart"]["result"][0]["meta"]
        out.update(found=True, price=m.get("regularMarketPrice"), currency=m.get("currency"),
                   exchange=m.get("fullExchangeName") or m.get("exchangeName"),
                   prev_close=m.get("previousClose") or m.get("chartPreviousClose"),
                   day_high=m.get("regularMarketDayHigh"), day_low=m.get("regularMarketDayLow"),
                   wk52_high=m.get("fiftyTwoWeekHigh"), wk52_low=m.get("fiftyTwoWeekLow"))
    except Exception as e:
        out["error"] = str(e)[:80]
    return out


# ---------------- the one-call bundle (routes by company type) ----------------

def company_intel(name: str, ticker: str | None = None) -> dict:
    """One call, routed: US public -> SEC financials + filings + market + percentile; else Form D
    + Wikidata; always identity (GLEIF) + Wikidata facts. Never raises; each source isolated."""
    r = _resolve_cik(name, ticker)
    bundle = {"company": name, "sources_used": []}

    def add(key, fn, *a):
        try:
            bundle[key] = fn(*a)
            bundle["sources_used"].append(key)
        except Exception as e:
            bundle[key] = {"error": str(e)[:60]}

    if r:                                          # US public
        bundle["kind"] = "us_public"
        add("financials", sec_financials, name, r[1])
        add("market", market_quote, r[1])
        add("filings", sec_filings, name, r[1], ["8-K", "10-K", "S-1", "SC 13D"])
        add("peer", peer_percentile, name, "revenue", r[1])
    else:
        bundle["kind"] = "private_or_other"
        add("funding", form_d_raises, name)
    add("facts", company_facts, name)
    add("identity", registry_identity, name)
    return bundle
