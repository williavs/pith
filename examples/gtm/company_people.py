"""Paint the best public picture of a company's PEOPLE — the roster a sales rep actually
wants: who works there and their titles, plus how to reach in.

This is the "using it right" example for the hardest GTM ask. The CORE makes it easy:
  - crawl_site already targets /team /leadership /people /about /founders /management
  - contact_evidence returns Person facts (name + jobTitle) with provenance across those pages
  - recipes.people() rosters them; recipes.owner_email() / the socials give the way in
The JUDGMENT and the framing live HERE, not in the core.

Honest boundary: pith is deterministic and public-only — it reads machine-readable people
(schema.org Person, the markup companies add for Google) but does NOT guess names out of prose
or scrape LinkedIn behind its wall. So the roster is exactly as good as the company's own
structured data. When it's empty, that's reported — not hidden — and the pointer is "go to
their LinkedIn," which a human/LLM does next. Best PUBLIC picture, not a fabricated one.

Run:  python examples/gtm/company_people.py https://stripe.com
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith.cli import contact_evidence, website_intel, _company_social
from pith import recipes


def company_picture(website: str) -> dict:
    ev = contact_evidence(website)
    facts = ev["facts"]
    socials = sorted({f.value for f in facts if f.kind == "social"})
    roster = recipes.people(facts)                       # names + titles from structured data
    owner = recipes.owner_email(facts, prefer=("owner", "person", "role"))
    try:
        intel = website_intel(website)
    except Exception:
        intel = {}
    return {
        "company_domain": ev["domain"],
        "pages_read": len(ev["coverage"].ok),
        "people": roster,                                # [{name, title, corroboration, sources}]
        "channels": {
            "best_email": owner.value if owner else None,
            "linkedin": _company_social(set(socials), ev["domain"].split(".")[0], "linkedin.com/company"),
            "socials": socials,
            "phones": [f.value for f in facts if f.kind == "phone"],
        },
        "tech": {"grade": intel.get("modernness_grade"), "builder": intel.get("builder")},
        "coverage_note": (
            f"{len(roster)} people from structured data across {len(ev['coverage'].ok)} pages"
            if roster else
            "No machine-readable team on this site (no schema.org Person). Deterministic public "
            "extraction can't paint a roster here — next step is their LinkedIn company page."
        ),
    }


def render(pic: dict) -> str:
    lines = [f"COMPANY: {pic['company_domain']}   ({pic['pages_read']} pages read)"]
    lines.append(f"tech: {pic['tech'].get('grade') or '?'} · {pic['tech'].get('builder') or '?'}")
    lines.append("\nPEOPLE:")
    if pic["people"]:
        for p in pic["people"]:
            lines.append(f"  {p['name']:28} {p['title'] or '—':28} (x{p['corroboration']})")
    else:
        lines.append("  (none — see coverage note)")
    c = pic["channels"]
    lines.append("\nHOW TO REACH IN:")
    lines.append(f"  best email: {c['best_email'] or '—'}")
    lines.append(f"  linkedin:   {c['linkedin'] or '—'}")
    lines.append(f"  phones:     {', '.join(c['phones']) or '—'}")
    lines.append(f"  socials:    {', '.join(c['socials'][:6]) or '—'}")
    lines.append(f"\n> {pic['coverage_note']}")
    return "\n".join(lines)


if __name__ == "__main__":
    site = sys.argv[1] if len(sys.argv) > 1 else "https://stripe.com"
    pic = company_picture(site)
    if "--json" in sys.argv:
        print(json.dumps(pic, indent=2))
    else:
        print(render(pic))
