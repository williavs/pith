"""Investigation pivot — the full OSINT waterfall over pith, on REAL public data.

Given one starting fact (an email), pith pivots outward through public sources:

    email ──► Gravatar profile ──► linked accounts (Twitter/LinkedIn/GitHub/...)
      │                              │
      │                              └─► username ──► profile enumeration across the web
      └─► verify_email (role? freemail? disposable?)                    │
                                                                        └─► identity
    any phone found ──► phone_intel (region, line type, carrier, E.164)     corroboration
                                                                            (resolve_person)

Every step is deterministic and public-only — no auth, no breach data, no scraping behind a
login. This is the pattern to copy for a real investigation: start from what you know, let
each result feed the next lookup, and keep the provenance.

Run:  python examples/investigate.py [email]
      python examples/investigate.py beau@dentedreality.com.au    # a real public Gravatar

Requires:  pip install 'pith[osint]'   (phonenumbers)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pith import verify_email
from pith.gravatar import gravatar_profile
from pith.phoneintel import phone_intel
from pith.profiles import enumerate_profiles


def investigate(email: str):
    print(f"\n┌─ INVESTIGATION START: {email}")

    # 1. Grade the email itself — deterministic quality signals.
    v = verify_email(email)
    tags = [k for k in ("is_role", "is_freemail", "is_disposable") if v.get(k)]
    print(f"│  verify_email: valid={v['valid_syntax']} domain={v.get('domain')} "
          f"{'· ' + ', '.join(tags) if tags else '· (personal)'}")

    # 2. Gravatar pivot — the single best legal email->accounts primitive.
    g = gravatar_profile(email)
    if not g.get("exists"):
        print("│  gravatar: no public profile for this email")
        print("└─ (dead end on Gravatar — try a known email, e.g. beau@dentedreality.com.au)")
        return
    print(f"│  gravatar: {g['display_name']} — {g.get('location') or 'location n/a'}")
    print(f"│           {g['profile_url']}")

    # 3. The linked accounts ARE the pivot — verified profiles the person attached themselves.
    print(f"│  linked accounts ({len(g['accounts'])}):")
    handles = set()
    for a in g["accounts"]:
        u = a.get("username")
        print(f"│    · {a['site']:12} {a['url']}" + (f"  (@{u})" if u else ""))
        if u:
            handles.add(u)

    # 4. Take a handle and enumerate its footprint across the web (existence + coverage).
    if handles:
        handle = sorted(handles)[0]
        print(f"│  enumerating handle '{handle}' across the web…")
        r = enumerate_profiles(handle, persona="technical", report=True)
        cov = r["coverage"]
        print(f"│    found {cov['found']} · not-found {cov['not_found']} · "
              f"inconclusive {cov['inconclusive']} (of {cov['checked']} checked)")
        for h in r["profiles"][:8]:
            flag = " [RESERVED HANDLE]" if h.get("reserved") else ""
            print(f"│    · {h['site']:14} {h['value']:4} {h['url']}{flag}")
        if cov["inconclusive_sites"]:
            print(f"│    could NOT verify (bot-walled): {', '.join(cov['inconclusive_sites'][:6])}")

    print("└─ END. Every datum above is public + deterministic; feed it to your LLM for synthesis.")


def phone_demo():
    """Phone intelligence on a spread of real number shapes — the upgrade to every number
    pith extracts."""
    print("\n┌─ PHONE INTELLIGENCE (offline, deterministic)")
    for n, region in [("+44 20 7946 0958", None), ("(212) 867-5309", None),
                      ("+91 98765 43210", None), ("+1 800 555 0100", None)]:
        d = phone_intel(n, region)
        print(f"│  {n:20} → {d['region']} · {d['line_type']:15} · {d.get('location') or '—':14} · {d['e164']}")
    print("└─ region + line-type (mobile vs landline vs toll-free) on any number, no lookups.")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "beau@dentedreality.com.au"
    investigate(email)
    phone_demo()
