"""Build a sales list — the GTM pipeline over pith, on REAL data.

Category + geo ──► directory_search ──► a list of real local businesses
                        │
      each business ──► website_intel  (tech stack + modernness grade A–F)
                        │
                   contact_evidence  (Facts: emails/phones/socials + WHOIS, corroborated)
                        │
                   recipes.owner_email / recipes.rank_phones  (YOUR judgment over evidence)
                        │
                   rank by "reachable + dated" ──► a prioritized sales list

This is the top-of-funnel for selling to small/mid businesses: pith finds the accounts,
grades how dated their site is (the pitch hook), and gathers the owner's contact EVIDENCE —
all public, all deterministic. pith returns Facts (never a 'primary' pick); this script
applies pith.recipes with a sales intent (prefer owner/person/role emails) to decide who to
reach. Output is JSON you can feed straight into a CRM or an LLM for pitch drafting.

Run:  python examples/gtm/build_sales_list.py "plumbers" "Tulsa, OK" 8
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.cli import directory_search, website_intel, contact_evidence
from pith import recipes

_GRADE_RANK = {"F": 0, "D": 1, "C": 2, "B": 3, "A": 4, "?": 5}


def build(category: str, location: str, limit: int = 8) -> list[dict]:
    print(f"┌─ directory_search: '{category}' in {location}", file=sys.stderr)
    businesses = directory_search(category, location, limit=limit * 2)
    print(f"│  {len(businesses)} businesses found", file=sys.stderr)

    leads = []
    for b in businesses:
        if not b.get("website"):
            continue
        try:
            intel = website_intel(b["website"])
        except Exception as e:
            print(f"│  skip {b['name']}: {str(e)[:40]}", file=sys.stderr)
            continue
        grade = intel.get("modernness_grade")
        ev = contact_evidence(b["website"])
        facts = ev["facts"]
        emails = [f for f in facts if f.kind == "email"]
        phones = recipes.rank_phones(facts)                       # ranked by corroboration
        socials = [f.value for f in facts if f.kind == "social"]
        # THE fix: use the recipe, not a raw type=="owner" filter (which returned None on real
        # leads whose best email was a person/role, not a literal "owner").
        best = recipes.owner_email(facts, prefer=("owner", "person", "role"))
        owner_email = best.value if best else None
        # score: dated site + reachable owner = hottest lead
        reach = (2 if owner_email else 1 if emails else 0) + (1 if phones else 0)
        score = (5 - _GRADE_RANK.get(grade, 5)) * 2 + reach
        leads.append({
            "name": b["name"], "website": b["website"], "address": b.get("address", ""),
            "grade": grade, "builder": intel.get("builder"), "responsive": intel.get("responsive"),
            "domain_age_years": intel.get("domain_age_years"),
            "owner_email": owner_email,
            "emails": [f.value for f in emails],
            "phones": [f.value for f in phones],
            "socials": socials,
            "score": score,
        })
        print(f"│  {b['name'][:30]:30} grade {grade} · {len(emails)}✉ "
              f"{len(phones)}☎ · score {score}", file=sys.stderr)
        if len(leads) >= limit:
            break

    leads.sort(key=lambda x: -x["score"])
    print(f"└─ {len(leads)} leads, ranked hottest-first\n", file=sys.stderr)
    return leads


if __name__ == "__main__":
    category = sys.argv[1] if len(sys.argv) > 1 else "plumbers"
    location = sys.argv[2] if len(sys.argv) > 2 else "Tulsa, OK"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    print(json.dumps(build(category, location, limit), indent=2))   # stdout = the JSON list
