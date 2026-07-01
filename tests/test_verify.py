"""verify_email — deterministic email signals, precision both directions. No SMTP, no API."""
from pith import verify_email


def test_valid_person_email():
    v = verify_email("matt.macinnis@rippling.com")
    assert v["valid_syntax"] and not v["is_role"] and not v["is_disposable"] and not v["has_alias"]
    assert v["domain"] == "rippling.com"


def test_role_account_flagged():
    for e in ["sales@acme.com", "info@acme.com", "support@acme.com", "no-reply@acme.com"]:
        assert verify_email(e)["is_role"], e
    assert not verify_email("john@acme.com")["is_role"]


def test_disposable_domain_flagged():
    # 0-mail.com is in the bundled disposable list
    assert verify_email("x@0-mail.com")["is_disposable"]
    assert not verify_email("x@rippling.com")["is_disposable"]


def test_plus_alias_and_role_strip():
    v = verify_email("sales+lead@acme.com")
    assert v["has_alias"] and v["is_role"]   # alias stripped before role check


def test_freemail_flags_owner_operator_addresses():
    # small-biz owner tells: gmail + ISP domains
    for e in ["mrcomfortohio@gmail.com", "blairheating@cinci.rr.com", "joe@comcast.net"]:
        assert verify_email(e)["is_freemail"], e
    # a corporate domain is NOT freemail
    assert not verify_email("owner@acmehvac.com")["is_freemail"]


def test_bad_syntax():
    for e in ["not-an-email", "a@b", "@nope.com", "spaces in@email.com", ""]:
        assert not verify_email(e)["valid_syntax"], e
