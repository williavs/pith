#!/usr/bin/env python3
"""leads_coverage — measure pith.leads provider coverage across a business-type x city matrix.

For each cell we record, per provider AND for the merged result:
  total count, % with website, % with phone, % with email.
For the merged result we also record cross-source agreement (fraction of merged records with
corroboration > 1) and mean confidence. Freshness is summarized from source_meta.update_frequency
(OSM elements carry a last-edit timestamp; the merged output doesn't need per-record stamps).

Cost control: radius_km=3 (small bbox = fast Overture download), time.sleep(1) between cells
(Nominatim asks <=1 req/s), each cell wrapped in try/except so one failure can't kill the sweep.

Overpass runs on all 12 cells. Overture (slow: ~15-90s/call) runs only on the 4 Phoenix cells
(one per category); merged cross-source numbers therefore only exist for those 4 cells.

Run:  uv run --with overturemaps python benchmarks/leads_coverage.py
Writes benchmarks/leads_coverage.json and prints a table to stdout.
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pith.leads import find_businesses  # noqa: E402

CATEGORIES = ["dentists", "restaurants", "plumbers", "gyms"]
CITIES = ["Phoenix, AZ", "Austin, TX", "Portland, OR"]
OVERTURE_CITY = "Phoenix, AZ"   # Overture only on this city (one cell per category)
RADIUS_KM = 3
LIMIT = 100
OUT_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leads_coverage.json")


def pct(num: int, den: int) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def field_stats(bizs: list[dict]) -> dict:
    n = len(bizs)
    web = sum(1 for b in bizs if b.get("website"))
    ph = sum(1 for b in bizs if b.get("phone"))
    em = sum(1 for b in bizs if b.get("email"))
    return {"count": n, "pct_website": pct(web, n), "pct_phone": pct(ph, n), "pct_email": pct(em, n)}


def merged_stats(bizs: list[dict]) -> dict:
    s = field_stats(bizs)
    n = len(bizs)
    corrob = sum(1 for b in bizs if b.get("corroboration", 0) > 1)
    confs = [b.get("confidence", 0.0) for b in bizs]
    s["agreement_rate"] = pct(corrob, n)              # % of merged records attested by >1 provider
    s["corroborated_count"] = corrob
    s["mean_confidence"] = round(sum(confs) / n, 3) if n else 0.0
    return s


_RETRYABLE = ("429", "504", "503", "502", "timed out", "timeout", "Gateway", "Too Many")


def call(category: str, city: str, sources, attempts: int = 6) -> dict:
    """find_businesses with backoff retry. The public Overpass endpoint (overpass-api.de) throttles
    (429) and sheds load (504) under bursty use — a lone spaced request returns 200, but several
    within a few seconds trip a per-IP cooldown. A provider error lands in coverage['errors'] rather
    than raising, so we retry the whole call with growing backoff until the requested providers come
    back clean (or we exhaust attempts). Geocode is process-cached so retries don't re-hit Nominatim."""
    last = None
    for i in range(attempts):
        r = find_businesses(category, city, sources=sources, limit=LIMIT, radius_km=RADIUS_KM)
        last = r
        errs = r["coverage"].get("errors", {})
        retryable = {p: e for p, e in errs.items() if any(t in str(e) for t in _RETRYABLE)}
        if not retryable:
            return r
        wait = 15 * (i + 1)   # 15,30,45,60,75s — enough to clear the Overpass cooldown
        print(f"    retry {i + 1}/{attempts - 1} after {wait}s (errors: {retryable})", flush=True)
        if i < attempts - 1:
            time.sleep(wait)
    return last


def run_cell(category: str, city: str, want_overture: bool) -> dict:
    cell: dict = {"category": category, "city": city, "overture_included": want_overture,
                  "providers": {}, "merged": None, "errors": {}, "geo": None}

    # Overpass alone (fast, all cells) — single-source merged == that provider's own yield.
    r = call(category, city, ["overpass"])
    cell["geo"] = r["geo"]["display"]
    cell["providers"]["overpass"] = field_stats(r["businesses"])
    cell["providers"]["overpass"]["ran"] = "overpass" in r["coverage"]["ran"]
    cell["providers"]["overpass"]["raw_count"] = r["coverage"]["counts"].get("overpass", 0)
    cell["errors"].update(r["coverage"].get("errors", {}))
    cell["_source_meta"] = r["coverage"]["source_meta"]

    if want_overture:
        # Overture alone -> its own yield.
        ro = call(category, city, ["overture"])
        cell["providers"]["overture"] = field_stats(ro["businesses"])
        cell["providers"]["overture"]["ran"] = "overture" in ro["coverage"]["ran"]
        cell["providers"]["overture"]["raw_count"] = ro["coverage"]["counts"].get("overture", 0)
        cell["errors"].update(ro["coverage"].get("errors", {}))
        # Both sources -> merged + cross-source agreement. Space it from the overpass-only call
        # above so the two Overpass hits don't burst into a throttle.
        time.sleep(5)
        rm = call(category, city, "auto")
        cell["merged"] = merged_stats(rm["businesses"])
        cell["merged"]["ran"] = rm["coverage"]["ran"]
        cell["merged"]["raw_counts"] = rm["coverage"]["counts"]
        cell["errors"].update(rm["coverage"].get("errors", {}))
    else:
        # Only overpass available for this cell — merged == overpass single-source.
        cell["merged"] = merged_stats(r["businesses"])
        cell["merged"]["ran"] = r["coverage"]["ran"]
        cell["merged"]["raw_counts"] = r["coverage"]["counts"]
    return cell


def main() -> int:
    results: dict = {"config": {"categories": CATEGORIES, "cities": CITIES,
                                "overture_city": OVERTURE_CITY, "radius_km": RADIUS_KM, "limit": LIMIT},
                     "cells": [], "source_meta": None}
    for category in CATEGORIES:
        for city in CITIES:
            want_overture = (city == OVERTURE_CITY)
            print(f"[cell] {category} @ {city}  (overture={'yes' if want_overture else 'no'})",
                  flush=True)
            try:
                cell = run_cell(category, city, want_overture)
                if results["source_meta"] is None:
                    results["source_meta"] = cell.pop("_source_meta")
                else:
                    cell.pop("_source_meta", None)
                results["cells"].append(cell)
            except Exception as e:  # one bad cell must not sink the sweep
                print(f"  ERROR: {type(e).__name__}: {e}", flush=True)
                results["cells"].append({"category": category, "city": city,
                                         "overture_included": want_overture,
                                         "providers": {}, "merged": None,
                                         "errors": {"cell": f"{type(e).__name__}: {str(e)[:300]}"}})
            time.sleep(2)  # polite to Nominatim/Overpass between cells (>=1 req/s)

    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2)

    print_tables(results)
    print(f"\nRaw results written to {OUT_JSON}")
    return 0


def print_tables(results: dict) -> None:
    print("\n" + "=" * 88)
    print("PER-PROVIDER YIELD  (count | %website | %phone | %email)")
    print("=" * 88)
    hdr = f"{'category':<12}{'city':<14}{'provider':<10}{'count':>7}{'%web':>8}{'%phone':>9}{'%email':>9}"
    print(hdr)
    print("-" * 88)
    for cell in results["cells"]:
        cat, city = cell["category"], cell["city"]
        if cell.get("errors", {}).get("cell"):
            print(f"{cat:<12}{city:<14}{'(cell errored: ' + cell['errors']['cell'][:40] + ')'}")
            continue
        for pname, st in cell.get("providers", {}).items():
            print(f"{cat:<12}{city:<14}{pname:<10}{st['count']:>7}"
                  f"{st['pct_website']:>8}{st['pct_phone']:>9}{st['pct_email']:>9}")

    print("\n" + "=" * 88)
    print("MERGED RESULT  (count | %web | %phone | %email | agree% (corrob>1) | mean_conf)")
    print("=" * 88)
    print(f"{'category':<12}{'city':<14}{'count':>7}{'%web':>7}{'%phone':>8}{'%email':>8}"
          f"{'agree%':>9}{'mean_cf':>9}  sources")
    print("-" * 88)
    for cell in results["cells"]:
        m = cell.get("merged")
        if not m:
            continue
        cat, city = cell["category"], cell["city"]
        src = "+".join(m.get("ran", []))
        print(f"{cat:<12}{city:<14}{m['count']:>7}{m['pct_website']:>7}{m['pct_phone']:>8}"
              f"{m['pct_email']:>8}{m['agreement_rate']:>9}{m['mean_confidence']:>9}  {src}")

    errs = {f"{c['category']}@{c['city']}": c["errors"] for c in results["cells"] if c.get("errors")}
    if errs:
        print("\nERRORS:")
        for k, v in errs.items():
            print(f"  {k}: {v}")

    sm = results.get("source_meta") or {}
    print("\nSOURCE META (freshness / reliability / license):")
    for pname, meta in sm.items():
        print(f"  [{pname}] update_frequency: {meta.get('update_frequency')}")
        print(f"           reliability:      {meta.get('reliability')}")
        print(f"           license:          {meta.get('license')}")


if __name__ == "__main__":
    raise SystemExit(main())
