"""Deterministic people extraction from team/about pages — names + titles + emails, no LLM.

schema.org Person is the high-confidence path (cli.contact_evidence folds it in). But most local
businesses publish their team as plain HTML — a headshot, a name, a role — with no machine-readable
markup, so a schema-only reader cancels out the majority of real decision-makers. This catches them.

Conservative by design: a person is emitted only when a proper-name pattern sits ADJACENT to a
role word or professional credential (same line or the next). That adjacency is the precision
knob — a sales rep can trust the roster — at the cost of recall on bare, unlabeled names. Names
that appear with no role are left in the raw `name` facts (nothing is hidden), just not promoted
here. Person-pattern emails (jane.smith@, jsmith@) are matched back to the people found.
"""
from __future__ import annotations

import re

# roles + credentials that mark a name as a business person (not a random capitalized phrase)
_ROLE_WORDS = (
    "owner", "co-owner", "founder", "co-founder", "cofounder", "president", "vice president",
    "ceo", "cfo", "coo", "cto", "cmo", "cio", "principal", "partner", "managing partner",
    "managing director", "managing member", "director", "manager", "office manager",
    "practice manager", "proprietor", "chair", "chairman", "chairwoman", "chief",
    "head", "associate", "counsel", "of counsel", "attorney", "lawyer", "paralegal",
    "agent", "realtor", "broker", "loan officer", "advisor", "adviser", "consultant",
    "dentist", "orthodontist", "endodontist", "periodontist", "hygienist", "physician",
    "doctor", "surgeon", "chiropractor", "optometrist", "therapist", "provider",
    "specialist", "coordinator", "esthetician", "stylist", "technician", "supervisor",
    "vp", "svp", "evp", "avp", "gm", "founder & ceo",
)
_CREDENTIALS = (
    "dds", "dmd", "md", "do", "dc", "od", "pa-c", "pa", "np", "rn", "rdh", "esq", "esquire",
    "cpa", "mba", "phd", "psyd", "lmt", "pt", "dpt", "dpm", "pharmd", "aprn", "lcsw", "cfp",
)
_ROLE_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _ROLE_WORDS) + r")\b", re.I)
_CRED_RE = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in _CREDENTIALS) + r")\b\.?", re.I)

# a person's name: optional honorific, then 2-3 capitalized tokens (allow a middle initial + O'/hyphen)
_NAME_RE = re.compile(
    r"(?:Dr|Mr|Mrs|Ms|Miss|Atty|Prof)\.?\s+"                                   # honorific -> strong signal
    r"[A-Z][A-Za-z'’.-]+(?:\s+[A-Z][A-Za-z'’.-]+){0,2}"
    r"|"
    r"[A-Z][a-z'’]+(?:\s+[A-Z]\.?)?(?:\s+(?:van|von|de|del|la|di|Mc|Mac|O'))?\s+[A-Z][A-Za-z'’-]+"
)
# capitalized words that are NOT names even when they fit the shape
_NOT_NAME = frozenset({
    "About Us", "Our Team", "Meet The", "Meet Our", "Contact Us", "Our Story", "Our Doctors",
    "Our Staff", "Learn More", "Read More", "View All", "Get Started", "Book Now", "Call Now",
    "Privacy Policy", "Terms Of", "New Patient", "New Patients", "Office Hours", "Site Map",
})
_NON_NAME_TOK = frozenset({"the", "our", "your", "about", "contact", "team", "meet", "welcome",
                           "home", "services", "service", "learn", "read", "view", "get", "book",
                           "call", "schedule", "hours", "location", "reviews", "menu", "search"})
# single role/credential words are titles, not names — a "name" containing one is the title line itself
_ROLE_TOKENS = frozenset(
    w for w in _ROLE_WORDS if " " not in w and "&" not in w
).union(_CREDENTIALS).union({"senior", "junior", "front", "back", "general", "new", "office", "practice"})
# org/department words — a "name" token that is one of these is a company/team, not a person
_ORG_TOKENS = frozenset({"recruiting", "group", "services", "service", "solutions", "realty",
                         "plumbing", "dental", "medical", "law", "associates", "partners",
                         "company", "department", "division", "marketing", "sales", "holdings",
                         "enterprises", "industries", "systems", "technologies", "consulting",
                         "management", "properties", "clinic", "center", "centre", "hospital",
                         "insurance", "financial", "capital", "ventures", "studio", "agency"})


def _clean_name(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip(" ,.-–—:|")
    s = re.sub(r"^(Dr|Mr|Mrs|Ms|Miss|Atty|Prof)\.?\s+", "", s).strip()
    return re.sub(r"['’]s\b", "", s).strip()          # drop possessive: "Ken Goodrich's" -> "Ken Goodrich"


def _plausible(name: str) -> bool:
    if name in _NOT_NAME or len(name) < 5:
        return False
    toks = name.split()
    if not (2 <= len(toks) <= 3):
        return False
    low = [t.lower().strip(".") for t in toks]
    if any(t in _NON_NAME_TOK or t in _ROLE_TOKENS or t in _ORG_TOKENS for t in low):
        return False                                   # role/org word => it's a title or company, not a name
    # at least two tokens must be real word-y names (not all initials)
    return sum(len(re.sub(r"[^A-Za-z]", "", t)) >= 2 for t in toks) >= 2


def _role_near(*chunks: str) -> str:
    """Return the role/credential phrase found in the given text chunks (title), or ''."""
    for c in chunks:
        if not c:
            continue
        m = _ROLE_RE.search(c) or _CRED_RE.search(c)
        if m:
            t = c.strip(" ,-–—:|·•\t")
            return t[:60] if len(t) <= 60 else m.group(0)
    return ""


def _email_name_match(email: str, name: str) -> bool:
    local = email.split("@")[0].lower()
    etoks = [t for t in re.split(r"[._+-]", local) if t]
    ntoks = [re.sub(r"[^a-z]", "", t.lower()) for t in name.split()]
    ntoks = [t for t in ntoks if len(t) >= 2]
    if not etoks or not ntoks:
        return False
    first, last = ntoks[0], ntoks[-1]
    joined = "".join(etoks)
    # jane.smith / jsmith / smithj / janesmith / jane_smith
    return (
        (first in etoks and last in etoks)
        or joined in (first + last, last + first)
        or (last in etoks and any(t == first[0] for t in etoks))
        or (first in etoks and any(t == last[0] for t in etoks))
        or joined == first[0] + last or joined == last + first[0]
    )


def is_probable_name(name: str) -> bool:
    """Lenient sanity for a name string from ANY source (schema.org included): reject only
    obvious non-names — bracketed placeholders, strings with lowercase connectors ('X and Y'),
    or too many tokens (a phrase, not a name). Real personal names (2-4 tokens) always pass.
    This is 'is this a person's name at all', not a judgment on WHO — no real person is dropped."""
    n = re.sub(r"\s+", " ", (name or "")).strip(" ,.-:|")
    if not n or "[" in n or "]" in n or "@" in n or "/" in n:
        return False
    toks = n.split()
    if not (2 <= len(toks) <= 4):
        return False
    if any(t.lower().strip(".") in {"and", "&", "of", "for", "the", "at"} for t in toks):
        return False
    # name run into a title: "WangCEO", "LavingiaFounder" — a token ending in a CamelCase run-on
    # whose trailing chunk is a role word. (Leaves real internal caps like DeShawn / McDonald alone.)
    for t in toks:
        m = re.search(r"[a-z]([A-Z][a-zA-Z]*)$", t)
        if m and m.group(1).lower() in _ROLE_TOKENS:
            return False
    return True


def extract_people(text: str, emails=(), source_url: str = "") -> list[dict]:
    """Team/about page text -> [{name, title, emails, source, method}]. See module docstring."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    found: dict[str, dict] = {}
    for i, line in enumerate(lines):
        if not line or len(line) > 200:                 # skip prose paragraphs; people sit on short lines
            continue
        for m in _NAME_RE.finditer(line):
            name = _clean_name(m.group(0))
            if not _plausible(name):
                continue
            after = line[m.end():]
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            title = _role_near(after, nxt, line[:m.start()])
            if not title:                               # no adjacent role -> not promoted (precision)
                continue
            rec = found.setdefault(name, {"title": "", "emails": set(), "source": source_url})
            if title and not rec["title"]:
                rec["title"] = title
    for e in emails:                                    # attach person-pattern emails to their person
        for name, rec in found.items():
            if _email_name_match(e, name):
                rec["emails"].add(e)
    return [{"name": n, "title": r["title"], "emails": sorted(r["emails"]),
             "source": r["source"], "method": "heuristic"}
            for n, r in found.items()]


if __name__ == "__main__":
    sample = (
        "Meet Our Team\n"
        "Dr. Aaron Jeziorski\nLead Dentist, DDS\n"
        "Jane A. Smith\nOffice Manager\njane.smith@practice.com\n"
        "John Doe, Founder & CEO\n"
        "Our Story\n"                                   # decoy heading — must not become a person
        "About Us\n"
        "Welcome to our practice where quality care and a friendly team make every visit easy."  # prose, no person
    )
    ppl = extract_people(sample, emails=["jane.smith@practice.com", "info@practice.com"])
    names = {p["name"]: p for p in ppl}
    assert "Aaron Jeziorski" in names and "DDS" in names["Aaron Jeziorski"]["title"], names
    assert "Jane A Smith" in names or "Jane A. Smith" in names, names
    jane = names.get("Jane A Smith") or names.get("Jane A. Smith")
    assert "jane.smith@practice.com" in jane["emails"], jane          # email matched to person
    assert "John Doe" in names and "Founder" in names["John Doe"]["title"]
    assert "Our Story" not in names and "About Us" not in names       # decoys rejected
    assert not any("Welcome" in n for n in names)                     # prose rejected
    print("people.py self-check OK:", [f"{p['name']} ({p['title']})" for p in ppl])
