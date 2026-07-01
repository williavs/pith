"""Adversarial edge cases surfaced by the fault-hunt workflow (2026-07). Each asserts a
CONFIRMED fault stays fixed: SSRF/LFI, intl/IDN, false-positive extraction, ccTLD domains."""
import pytest

from pith.core import _guard_url, UnsafeURL
from pith.cli import _registrable, _company_emails
from pith.extract import phones, socials, emails, verify_email


# --- fetch security: no file read, no SSRF to internal hosts ---
@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "gopher://x", "ftp://h/f", "data:text/html,x",
    "http://127.0.0.1/", "http://localhost/", "http://169.254.169.254/",
    "http://10.0.0.1/", "http://192.168.1.1/", "http://[::1]/", "http://0.0.0.0/",
])
def test_guard_blocks_unsafe(url):
    with pytest.raises(UnsafeURL):
        _guard_url(url)


def test_guard_allows_public():
    assert _guard_url("https://example.com/") == "https://example.com/"


# --- international phones extracted (E.164), junk dropped ---
def test_intl_phones():
    assert phones("UK +44 20 7946 0958") == ["+442079460958"]
    assert phones("India +91 98765 43210") == ["+919876543210"]
    assert phones("call +1 415 555 1234") == ["(415) 555-1234"]      # +1 US normalizes to NANP


def test_phone_false_positives_dropped():
    assert phones("SKU 100-200-3000") == []            # invalid NANP area/exchange
    assert phones("invoice 111-222-3333") == []
    assert phones("Resolution 1920 x 1080") == []
    assert phones("(555) 555-5555") == []              # reserved placeholder
    assert phones("Call us at 918-555-0142.") == ["(918) 555-0142"]  # trailing period kept


# --- IDN / unicode emails accepted by verify; length capped ---
def test_idn_email():
    assert verify_email("josé@example.com")["valid_syntax"] is True
    assert verify_email("用户@例子.公司")["valid_syntax"] is True
    assert verify_email("notanemail")["valid_syntax"] is False
    assert verify_email("a@b")["valid_syntax"] is False


# --- email extraction: real kept, filenames/placeholders dropped ---
def test_email_extraction_quality():
    assert "john.lastname@acme.com" in emails("reach john.lastname@acme.com")
    assert emails("logo@2x.png") == []
    assert emails("report@final.doc") == []
    assert emails("your@example.com") == []


# --- socials: profiles kept, nav/tracking/permalinks dropped ---
def test_socials_quality():
    assert socials("https://facebook.com/tr?id=1") == []
    assert socials("https://github.com/pricing") == []
    assert socials("https://instagram.com/p/Cx123/") == []
    assert socials("https://github.com/torvalds") == ["https://github.com/torvalds"]


# --- ccTLD registrable domain + company-email matching ---
def test_cctld_registrable():
    assert _registrable("https://acme.co.uk") == "acme.co.uk"
    assert _registrable("http://shop.acme.co.uk") == "acme.co.uk"
    assert _registrable("https://acme.com") == "acme.com"


def test_company_emails_no_suffix_bleed():
    got = _company_emails(["ceo@acme.co.uk", "x@notacme.co.uk", "spam@other.co.uk"], "https://acme.co.uk")
    assert got == ["ceo@acme.co.uk"]
