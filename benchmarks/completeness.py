"""How complete is a lead from the FREE keyless stack — and what's genuinely missing?

The coverage benchmark (leads_coverage.py) measured raw POI fields. This measures the real
ceiling: keyless POI (Overpass+Overture) PLUS pith's website enrichment (crawl the business's
own site for contacts/socials/people/schema.org). The site is the richest free source — a lead
looks thin from POI alone and much fuller after enrichment.

Output: per-requirement-field fill rate for POI-only vs POI+enriched, and a gap map naming which
fields the free stack cannot fill (→ which keyed API would).

Run:  uv run --with overturemaps python benchmarks/completeness.py [category] [location] [n]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pith import Extractor
from pith.cli import contact_evidence
from pith.leads import find_businesses
from pith.recipes import owner_email

# A "full lead" — what a sales record should carry. Grouped by who can fill it.
REQUIREMENT = {
    "core":        ["name", "category", "address", "phone", "website"],
    "contact":     ["email", "owner_email", "socials", "linkedin"],
    "people":      ["decision_maker", "title"],
    "firmographic": ["hours", "rating", "employees", "founded"],
}
# fields no free source reliably fills (measured expectation, verified by the run)
KNOWN_GAPS = {"rating", "employees", "founded"}


def _decision_maker(structured):
    """First schema.org Person carrying a jobTitle -> (name, title). The free decision-maker."""
    for s in structured:
        types = s.get("@type", "")
        if "Person" in str(types) and s.get("jobTitle"):
            return s.get("name", ""), s.get("jobTitle", "")
    return "", ""


def _hours(structured):
    for s in structured:
        h = s.get("openingHours") or s.get("openingHoursSpecification")
        if h:
            return True
    return False


def _linkedin(socials):
    return any("linkedin.com" in s for s in socials)


def enrich(poi: dict) -> dict:
    """POI record -> the full field set the free stack can produce for it."""
    rec = dict(poi)
    site = poi.get("website") or ""
    if not site:
        return rec
    if not site.startswith("http"):
        site = "https://" + site
    try:
        ev = contact_evidence(site, workers=4)
        emails = [f.value for f in ev["facts"] if f.kind == "email"]
        phones = [f.value for f in ev["facts"] if f.kind == "phone"]
        best = owner_email(ev["facts"])
        rec["email"] = emails[0] if emails else rec.get("email", "")
        rec["owner_email"] = best.value if best else ""
        rec["phone"] = rec.get("phone") or (phones[0] if phones else "")
        r = Extractor().extract([site]).results[0]
        rec["socials"] = r.socials
        rec["linkedin"] = "yes" if _linkedin(r.socials) else ""
        rec["address"] = rec.get("address") or (r.addresses[0] if r.addresses else "")
        dm, title = _decision_maker(r.structured)
        rec["decision_maker"], rec["title"] = dm, title
        rec["hours"] = "yes" if _hours(r.structured) else ""
    except Exception as e:
        rec["_enrich_error"] = str(e)[:80]
    return rec


def _filled(rec: dict, field: str) -> bool:
    v = rec.get(field)
    return bool(v) and v not in ("", [], "?", None)


def run(category="dentists", location="Phoenix, AZ", n=10):
    print(f"# Completeness: {category} in {location} (n={n})\n")
    res = find_businesses(category, location, sources="auto", limit=n * 3, has_website=True)
    sample = res["businesses"][:n]
    print(f"sampled {len(sample)} businesses with a website "
          f"(of {res['coverage'].get('merged_total')} merged)\n")

    all_fields = [f for grp in REQUIREMENT.values() for f in grp]
    poi_fill = {f: 0 for f in all_fields}
    enr_fill = {f: 0 for f in all_fields}

    for i, biz in enumerate(sample, 1):
        for f in all_fields:                      # POI-only
            if _filled(biz, f):
                poi_fill[f] += 1
        rec = enrich(biz)
        for f in all_fields:                      # POI + enrichment
            if _filled(rec, f):
                enr_fill[f] += 1
        dm = f"{rec.get('decision_maker','')} ({rec.get('title','')})" if rec.get("decision_maker") else "-"
        print(f"  {i:2}. {biz['name'][:34]:34} email={rec.get('owner_email') or rec.get('email') or '-':30.30} dm={dm}")

    tot = len(sample) or 1
    print(f"\n{'field':16} {'group':13} {'POI':>6} {'+enrich':>8}  gap")
    print("-" * 52)
    for grp, fields in REQUIREMENT.items():
        for f in fields:
            p, e = 100 * poi_fill[f] // tot, 100 * enr_fill[f] // tot
            gap = "KEYED/PAID" if f in KNOWN_GAPS else ("" if e >= 60 else "thin")
            print(f"{f:16} {grp:13} {p:5}% {e:7}%  {gap}")

    lift = {f: enr_fill[f] - poi_fill[f] for f in all_fields}
    top = sorted(lift.items(), key=lambda x: -x[1])[:5]
    print("\nBiggest enrichment lift (POI->+enrich, count of n):")
    for f, d in top:
        print(f"  +{d:2}  {f}")
    print("\nKnown gaps (no free source fills these reliably):")
    for f in KNOWN_GAPS:
        print(f"  {f:12} -> Yelp/Google (rating/reviews/hours), or B2B firmographic API (employees/founded)")
    return {"sample": len(sample), "poi_fill": poi_fill, "enr_fill": enr_fill}


if __name__ == "__main__":
    cat = sys.argv[1] if len(sys.argv) > 1 else "dentists"
    loc = sys.argv[2] if len(sys.argv) > 2 else "Phoenix, AZ"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    run(cat, loc, n)
