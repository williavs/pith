"""Build a sales list — the GTM pipeline over pith, on REAL data.

Category + geo ──► directory_search ──► a list of real local businesses
                        │
      each business ──► website_intel  (tech stack + modernness grade A–F)
                        │
                   find_contact  (owner email/phone/socials, WHOIS)
                        │
                   rank by "reachable + dated" ──► a prioritized sales list

This is the top-of-funnel for selling to small/mid businesses: pith finds the accounts,
grades how dated their site is (the pitch hook), and digs the owner's contact — all public,
all deterministic. Output is JSON you can feed straight into a CRM or an LLM for pitch drafting.

Run:  python examples/build_sales_list.py "plumbers" "Tulsa, OK" 8
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pith.cli import directory_search, website_intel, find_contact

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
        contact = find_contact(b["website"])
        owner_email = next((e["email"] for e in contact["emails"] if e["type"] == "owner"), None)
        # score: dated site + reachable owner = hottest lead
        reach = (2 if owner_email else 1 if contact["emails"] else 0) + (1 if contact["phones"] else 0)
        score = (5 - _GRADE_RANK.get(grade, 5)) * 2 + reach
        leads.append({
            "name": b["name"], "website": b["website"], "address": b.get("address", ""),
            "grade": grade, "builder": intel.get("builder"), "responsive": intel.get("responsive"),
            "domain_age_years": intel.get("domain_age_years"),
            "owner_email": owner_email,
            "emails": [e["email"] for e in contact["emails"]],
            "phones": [p["number"] for p in contact["phones"]],
            "socials": contact["socials"],
            "score": score,
        })
        print(f"│  {b['name'][:30]:30} grade {grade} · {len(contact['emails'])}✉ "
              f"{len(contact['phones'])}☎ · score {score}", file=sys.stderr)
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
