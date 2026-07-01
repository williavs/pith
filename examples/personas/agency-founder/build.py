"""Agency-founder lead pipeline over pith (all public, all deterministic).

  directory_search(cat, loc)  -> real local businesses
  website_intel(url)          -> modernness grade + dated_signals (the pitch hook)
  find_contact(url)           -> owner email / phone / socials

Keeps only DATED sites (grade C/D/F), ranks the dated ones by how reachable the
owner is, writes the top 5 to opportunities.json next to this file.

Run:  .venv/bin/python examples/personas/agency-founder/build.py
"""
import json, os, sys, time
from pith.cli import directory_search, website_intel, find_contact

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opportunities.json")
loc = "Wichita, KS"
cats = ["roofing", "plumbers", "hvac"]

seen, uniq = set(), []
for cat in cats:
    for b in directory_search(cat, loc, limit=20):
        w = b.get("website")
        if not w:
            continue
        dom = w.split("//")[-1].split("/")[0].replace("www.", "")
        if dom in seen:
            continue
        seen.add(dom)
        b["_cat"] = cat
        uniq.append(b)
print(f"unique-with-site: {len(uniq)}", file=sys.stderr)

graded = []
for b in uniq:
    t = time.time()
    try:
        intel = website_intel(b["website"])
    except Exception as e:
        print(f"skip intel {b['name']}: {e}", file=sys.stderr)
        continue
    g = intel.get("modernness_grade")
    print(f"{b['_cat']:8} {b['name'][:30]:30} grade {g} score {intel.get('modernness_score')} "
          f"resp={intel.get('responsive')} builder={intel.get('builder')} "
          f"dated={intel.get('dated_signals')} age={intel.get('domain_age_years')} "
          f"[{round(time.time()-t,1)}s]", file=sys.stderr)
    graded.append((b, intel))

dated = [(b, i) for b, i in graded if i.get("modernness_grade") in ("C", "D", "F")]
print(f"\ndated C/D/F: {len(dated)}", file=sys.stderr)

rows = []
for b, intel in dated:
    t = time.time()
    contact = find_contact(b["website"])
    owner_email = next((e["email"] for e in contact["emails"] if e.get("type") in ("owner", "person")), None)
    reach = (2 if owner_email else 1 if contact["emails"] else 0) + (1 if contact["phones"] else 0) + (1 if contact["socials"] else 0)
    print(f"contact {b['name'][:28]:28} {len(contact['emails'])} mail "
          f"{len(contact['phones'])} phone socials={len(contact['socials'])} reach={reach} "
          f"[{round(time.time()-t,1)}s]", file=sys.stderr)
    rows.append((reach, b, intel, contact, owner_email))

rows.sort(key=lambda r: -r[0])
out = []
for reach, b, intel, contact, owner_email in rows[:5]:
    out.append({
        "business": b["name"],
        "category": b["_cat"],
        "website": b["website"],
        "address": b.get("address", ""),
        "grade": intel.get("modernness_grade"),
        "modernness_score": intel.get("modernness_score"),
        "builder": intel.get("builder"),
        "framework": intel.get("framework"),
        "responsive": intel.get("responsive"),
        "https": intel.get("https"),
        "copyright_year": intel.get("copyright_year"),
        "domain_age_years": intel.get("domain_age_years"),
        "dated_signals": intel.get("dated_signals"),
        "owner_email": owner_email,
        "emails": [e["email"] for e in contact["emails"]],
        "phones": [p["number"] for p in contact["phones"]],
        "socials": contact["socials"],
    })

json.dump(out, open(OUT, "w"), indent=2)
print(f"\nWROTE {len(out)} opportunities -> {OUT}", file=sys.stderr)
