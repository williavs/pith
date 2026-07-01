"""OSINT capabilities. phone_intel is fully offline/deterministic (libphonenumber) so it runs
in the normal suite; the Gravatar tests hit the network and are marked live."""
import pytest

from pith.phoneintel import phone_intel


def test_phone_intel_international():
    uk = phone_intel("+44 20 7946 0958")
    assert uk["valid"] and uk["region"] == "GB" and uk["line_type"] == "fixed_line"
    assert uk["e164"] == "+442079460958" and uk["location"] == "London"
    inx = phone_intel("+91 98765 43210")
    assert inx["valid"] and inx["region"] == "IN" and inx["line_type"] == "mobile"


def test_phone_intel_us_and_toll_free():
    us = phone_intel("(212) 867-5309")               # no +, assumes US
    assert us["valid"] and us["region"] == "US" and us["assumed_region"] == "US"
    assert us["e164"] == "+12128675309"
    tf = phone_intel("+1 800 555 0100")
    assert tf["line_type"] == "toll_free"


def test_phone_intel_region_override():
    gb = phone_intel("020 7946 0958", region="GB")   # national format needs a region
    assert gb["valid"] and gb["region"] == "GB"


def test_phone_intel_invalid():
    assert phone_intel("notaphone")["valid"] is False
    assert phone_intel("12345")["valid"] is False


@pytest.mark.live
def test_gravatar_real_profile():
    from pith.gravatar import gravatar_profile
    g = gravatar_profile("beau@dentedreality.com.au")   # a real, long-standing public Gravatar
    assert g["exists"] and g["display_name"]
    assert any(a["site"] for a in g["accounts"])         # has linked accounts


@pytest.mark.live
def test_gravatar_nonexistent():
    from pith.gravatar import gravatar_profile
    assert gravatar_profile("no-such-user-zzq9@example.invalid")["exists"] is False
    assert gravatar_profile("notanemail")["exists"] is False
