"""List-cleaner sell-logic + the email deliverability primitive. Offline (the quality tiers are
pure; the MX/resolve lookups are monkeypatched)."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "list_clean", Path(__file__).resolve().parents[1] / "examples" / "list-cleaner" / "clean.py")
clean = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clean)


def _row(**kw):
    base = dict(email_syntax=True, is_disposable=False, is_role=False, is_freemail=False,
                domain_resolves=True, has_mx=True)
    base.update(kw)
    return base


def test_quality_tiers():
    assert clean._quality(_row()) == "sellable"
    assert clean._quality(_row(email_syntax=False)) == "dead"
    assert clean._quality(_row(is_disposable=True)) == "dead"
    assert clean._quality(_row(has_mx=False)) == "dead"                 # domain won't take mail
    assert clean._quality(_row(has_mx=None, domain_resolves=False)) == "dead"  # no MX known + dead domain
    assert clean._quality(_row(has_mx=None, domain_resolves=True)) == "sellable"  # MX unknown but domain alive
    assert clean._quality(_row(is_role=True)) == "risky"               # deliverable but info@-style
    assert clean._quality(_row(is_freemail=True)) == "risky"           # deliverable but gmail, not biz


def test_verify_email_mx_and_domain(monkeypatch):
    from pith import verify_email
    import pith.extract as ex
    ex._domain_resolves.cache_clear()
    ex._domain_has_mx.cache_clear()
    monkeypatch.setattr(ex, "_domain_resolves", lambda d: d != "dead.example")
    monkeypatch.setattr(ex, "_domain_has_mx", lambda d: True if d == "acme.com" else False)
    v = verify_email("jane@acme.com", check_domain=True, check_mx=True)
    assert v["valid_syntax"] and v["domain_resolves"] is True and v["has_mx"] is True
    v2 = verify_email("x@dead.example", check_domain=True, check_mx=True)
    assert v2["domain_resolves"] is False and v2["has_mx"] is False
    # without the flags, no network keys are added (fast offline path)
    v3 = verify_email("jane@acme.com")
    assert "has_mx" not in v3 and "domain_resolves" not in v3
