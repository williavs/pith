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


# --- schema.org structured: parentage scoping for both Person and Org ---
def test_structured_parentage():
    from pith.extract import structured, enrich
    # ProfilePage subject Person (mainEntity) kept
    h = '<script type="application/ld+json">{"@type":"ProfilePage","mainEntity":{"@type":"Person","name":"Jane Owner"}}</script>'
    assert "Jane Owner" in [e.get("name") for e in structured(h)]
    # publisher Org is KEPT but labeled (rel=publisher) — data not hidden; the business Org is rel=""
    h2 = '<script type="application/ld+json">{"@type":"LocalBusiness","name":"Joes","publisher":{"@type":"Organization","name":"WP VIP"}}</script>'
    by_name = {e["name"]: e.get("rel") for e in structured(h2)}
    assert by_name.get("Joes") == "" and by_name.get("WP VIP") == "publisher"   # kept, correctly labeled
    # the business contact fold does NOT attribute the publisher's data to the page
    assert "WP VIP" not in enrich("", h2)["socials"]
    # malformed dict telephone not stringified; schema phone canonicalized + deduped
    assert enrich("", '<script type="application/ld+json">{"@type":"Organization","name":"X","telephone":{"d":"x"}}</script>')["phones"] == []
    assert enrich("<p>(212) 867-5309</p>", '<script type="application/ld+json">{"@type":"Organization","name":"Y","telephone":"212-867-5309"}</script>')["phones"] == ["(212) 867-5309"]


def test_verify_email_length_cap():
    assert verify_email("x" * 300 + "@example.org")["valid_syntax"] is False
    assert verify_email("a" * 65 + "@x.com")["valid_syntax"] is False


# --- resolve identity: no name conflation, freemail not company, confidence by quality ---
def test_resolve_no_name_conflation():
    from pith.resolve import Target, score
    from pith.core import Result
    r = Result(url="https://x.com/j")
    r.structured = [{"@type": "Person", "name": "Johnathan Smithson"}]
    assert "FULL-NAME" not in score(Target(name="John Smith"), r)["signals"]


def test_resolve_freemail_not_company():
    from pith.resolve import Target, score
    from pith.core import Result
    r = Result(url="https://x.com/s")
    r.emails = ["someone@gmail.com"]
    assert "COMPANY-DOMAIN" not in score(Target(name="A B", website="https://gmail.com"), r)["signals"]


def test_person_title_inferred_from_schema_parent():
    from pith.extract import structured
    # no jobTitle, but placed under founder -> title is Founder
    h = '<script type="application/ld+json">{"@type":"Organization","name":"Acme","founder":{"@type":"Person","name":"Jane Doe"}}</script>'
    assert [(e["name"], e.get("jobTitle")) for e in structured(h)] == [("Acme", None), ("Jane Doe", "Founder")]
    # explicit jobTitle is not overwritten
    h2 = '<script type="application/ld+json">{"@type":"Organization","name":"A","founder":{"@type":"Person","name":"Sam","jobTitle":"CEO"}}</script>'
    assert ("Sam", "CEO") in [(e["name"], e.get("jobTitle")) for e in structured(h2)]


def test_crawl_site_is_ssrf_guarded():
    # crawl_site (the first fetch of every contact_evidence run) must honor the guard.
    from pith.cli import crawl_site
    from pith.core import UnsafeURL
    for bad in ["http://127.0.0.1/", "file:///etc/passwd", "http://169.254.169.254/"]:
        with pytest.raises(UnsafeURL):
            crawl_site(bad)


def test_socials_reject_subdomains_and_nav():
    # site chrome (api./docs./collector. subdomains, bare-domain nav slugs) is not a profile
    from pith.extract import socials
    html = " ".join(f'<a href="{u}">x</a>' for u in [
        "https://github.com/sindresorhus", "https://docs.github.com/site-policy",
        "https://collector.github.com/github", "https://github.com/why-github"])
    assert socials(html) == ["https://github.com/sindresorhus"]


def test_fediverse_handle_not_email():
    from pith.extract import emails
    assert emails("ping x@mastodon.social") == []
    assert emails("real jane@acme.com") == ["jane@acme.com"]


def test_whois_proxy_emails_dropped():
    from pith.extract import _junk_email
    assert _junk_email("abc@acme.com.whoisproxy.org")           # privacy-proxy host
    assert _junk_email("x@foo.whoisguard.com")
    assert _junk_email("a" * 40 + "0@vercel.com")               # long-hex obfuscation local
    assert not _junk_email("jane@acme.com")


def test_name_like_excludes_team_mailboxes():
    from pith.cli import _email_type_scoped
    assert _email_type_scoped("jane.diaz@acme.com", "acme.com") == "person"
    assert _email_type_scoped("security-internal@acme.com", "acme.com") == "functional"


def test_resolve_backlink_aliasing_and_self_reference():
    # both real investigators found these: x.com must alias to twitter; a self-URL anchor must
    # NOT count as corroboration.
    from pith.resolve import Target, score
    from pith.core import Result
    gh = Result(url="https://github.com/beau")
    gh.socials = ["https://twitter.com/beau", "https://github.com/beau"]
    assert "BACKLINK" in score(Target(name="Beau X", anchors={"https://x.com/beau"}), gh)["signals"]
    assert "BACKLINK" not in score(Target(name="Beau X", anchors={"https://github.com/beau"}), gh)["signals"]


# --- profiles: handle sanitized, coverage reported ---
def test_profiles_handle_validation():
    from pith.profiles import enumerate_profiles
    for bad in ["torvalds/../../linus", "a b", "x?y=1", "foo/bar", ""]:
        with pytest.raises(ValueError):
            enumerate_profiles(bad)
