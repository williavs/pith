"""Deterministic people extraction (pith/people.py) — the decision-maker wing. All offline:
name+role heuristics, precision guards, email->person matching, and the schema-name sanity gate."""
from pith.people import extract_people, is_probable_name, _plausible, _email_name_match


def test_extract_name_title_pairs():
    text = ("Meet Our Team\n"
            "Dr. Aaron Jeziorski\nLead Dentist, DDS\n"
            "John Doe, Founder & CEO\n"
            "Sarah Chen\nManaging Partner")
    ppl = {p["name"]: p for p in extract_people(text)}
    assert "Aaron Jeziorski" in ppl and "DDS" in ppl["Aaron Jeziorski"]["title"]
    assert "John Doe" in ppl and "Founder" in ppl["John Doe"]["title"]
    assert "Sarah Chen" in ppl and "Partner" in ppl["Sarah Chen"]["title"]


def test_requires_adjacent_role_for_precision():
    # a bare name with no nearby role is NOT promoted (precision > recall)
    assert extract_people("Jane Smith\nWe love our community.") == []
    assert extract_people("Contact Jane Smith for details.") == []


def test_rejects_decoys_and_roles_and_orgs():
    for junk in ("Our Story", "About Us", "Meet The", "Lead Dentist", "Office Manager",
                 "Goettl Recruiting", "Dental Group"):
        assert not _plausible(junk), junk
    assert _plausible("Aaron Jeziorski") and _plausible("Sarah J Chen")


def test_possessive_stripped():
    ppl = extract_people("Ken Goodrich's\nFormer Owner & CEO")
    assert any(p["name"] == "Ken Goodrich" for p in ppl)


def test_email_matched_to_person():
    ppl = extract_people("Jane Smith\nOwner\njane.smith@acme.com",
                         emails=["jane.smith@acme.com", "info@acme.com"])
    jane = next(p for p in ppl if p["name"] == "Jane Smith")
    assert jane["emails"] == ["jane.smith@acme.com"]      # personal matched, info@ not attached


def test_email_name_match_patterns():
    assert _email_name_match("jane.smith@x.com", "Jane Smith")
    assert _email_name_match("jsmith@x.com", "Jane Smith")
    assert _email_name_match("janesmith@x.com", "Jane Smith")
    assert not _email_name_match("info@x.com", "Jane Smith")
    assert not _email_name_match("bob@x.com", "Jane Smith")


def test_is_probable_name_gate():
    assert is_probable_name("Aaron Jeziorski")
    assert is_probable_name("Mary Jane Watson")
    assert not is_probable_name("Dr. [Name]")                         # bracketed placeholder
    assert not is_probable_name("Gust and Adam Goettl Master Plumber")  # phrase (>4 tok + 'and')
    assert not is_probable_name("Solutions")                          # single token
    assert not is_probable_name("john@acme.com")                      # an email, not a name
