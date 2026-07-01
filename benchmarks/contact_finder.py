"""Contact finder — the real GTM job: given a small/mid business, dig the owner's public
contact (email, phone, socials). Uses pith's CLEAN extractors (tel:-only phones, verified
emails) + WHOIS registrant data — the sources that actually carry small-biz owner contact.

Small-mid owners publish what big-co execs hide: a cell on the contact page, an email on
the about page, a real registrant in WHOIS (privacy often never enabled). This targets THAT.

Run:  ../.venv/bin/python contact_finder.py https://smallbiz.com "Biz Name"
"""
import subprocess
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pith import Extractor, verify_email
from pith.cli import crawl_site, _registrable


def whois_contact(domain):
    """Registrant email/phone/name from WHOIS — real for small biz that never enabled privacy."""
    try:
        out = subprocess.run(["whois", domain], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return {}
    _PROXY = ("domains by proxy", "registration private", "privacy", "redacted", "whoisguard",
              "perfect privacy", "contactdomainowner", "/whois", "withheld", "not disclosed")
    got = {}
    for line in out.splitlines():
        m = re.match(r"\s*(Registrant Email|Registrant Phone|Registrant Name|Registrant Organization)\s*:\s*(.+)", line, re.I)
        if m:
            key = m.group(1).split()[-1].lower()
            val = m.group(2).strip()
            if val and key not in got:
                got[key] = val
    # if any field is a privacy proxy, the whole record is shielded — drop it (the phone is
    # the proxy's, not the owner's).
    if any(p in v.lower() for v in got.values() for p in _PROXY):
        return {}
    return got


def find(website, name=""):
    domain = _registrable(website)
    print(f"CONTACT DIG: {name or domain}  ({website})\n{'='*60}")
    ex = Extractor()
    targets = crawl_site(website, limit=8)   # homepage + contact/about/team
    out = ex.extract([u for _, u in targets], concurrency=4)
    emails, phones, socials = set(), set(), set()
    for r in out.results:
        emails |= set(r.emails)
        phones |= set(r.phones)      # tel: links only — clean
        socials |= set(r.socials)

    print(f"crawled {len(out.results)} pages\n")
    print("EMAILS (classified — best contact first):")
    # rank: freemail owner-operator > on-domain person > on-domain role. That's the sales value order.
    def rank(e):
        v = verify_email(e)
        if v.get("is_freemail"):
            return (0, "OWNER (freemail)")
        if e.split("@")[-1].endswith(domain) and not v["is_role"]:
            return (1, "person @company")
        if e.split("@")[-1].endswith(domain):
            return (2, "role @company")
        return (3, "other")
    for e in sorted(emails, key=rank) or ["(none on the site)"]:
        r_, tag = rank(e) if "@" in e else (9, "")
        print(f"  {e:34} [{tag}]" if "@" in e else f"  {e}")
    print(f"\nPHONES (tel: links): {sorted(phones) or '(none published)'}")
    print(f"SOCIALS: {sorted(socials)[:6]}")

    who = whois_contact(domain)
    print(f"\nWHOIS registrant: {who or '(redacted / privacy on)'}")


if __name__ == "__main__":
    website = sys.argv[1] if len(sys.argv) > 1 else "https://basecamp.com"
    name = sys.argv[2] if len(sys.argv) > 2 else ""
    find(website, name)
