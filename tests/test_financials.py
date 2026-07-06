"""Financial data. The period-selection + resolution logic is deterministic (offline); the
live SEC/GLEIF/Wikidata/Yahoo calls are marked live."""
import pytest

from pith import financials as F


def test_latest_picks_annual_not_quarterly():
    # the bug the docs caught: naive max-by-date grabs a 10-Q quarter; must pick the 10-K year.
    gaap = {"Revenues": {"units": {"USD": [
        {"start": "2026-02-01", "end": "2026-04-30", "val": 264, "form": "10-Q", "filed": "2026-06-02", "fy": 2027},  # quarter (newest end)
        {"start": "2025-02-01", "end": "2026-01-31", "val": 955, "form": "10-K", "filed": "2026-03-17", "fy": 2026},  # full year
    ]}}}
    v = F._latest(gaap, ["Revenues"], instantaneous=False)
    assert v["value"] == 955 and v["form"] == "10-K"        # annual, not the 264 quarter


def test_latest_instantaneous_balance_sheet():
    gaap = {"Assets": {"units": {"USD": [
        {"end": "2026-01-31", "val": 1722, "form": "10-K", "filed": "2026-03-17"},
        {"end": "2025-01-31", "val": 1400, "form": "10-K", "filed": "2025-03-17"},
    ]}}}
    assert F._latest(gaap, ["Assets"], instantaneous=True)["value"] == 1722   # latest year-end


def test_resolve_cik(monkeypatch):
    monkeypatch.setattr(F, "_TICKERS", [{"cik_str": 1653482, "ticker": "GTLB", "title": "Gitlab Inc."},
                                        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}])
    assert F._resolve_cik("x", ticker="gtlb")[0] == "0001653482"
    assert F._resolve_cik("Apple Inc.")[1] == "AAPL"
    assert F._resolve_cik("gitlab")[2] == "Gitlab Inc."      # substring name
    assert F._resolve_cik("Stripe") is None                 # private -> no CIK
    # a mixed-case NAME must not collide with a coincidental ticker (Ramp -> ticker RAMP/LiveRamp)
    monkeypatch.setattr(F, "_TICKERS", [{"cik_str": 733269, "ticker": "RAMP", "title": "LiveRamp Holdings, Inc."},
                                        {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}])
    assert F._resolve_cik("Ramp") is None                   # private co, not LiveRamp
    assert F._resolve_cik("AAPL")[1] == "AAPL"              # deliberate all-caps ticker still resolves
    assert F._resolve_cik("LiveRamp Holdings, Inc.")[1] == "RAMP"   # real title still matches


def test_days_and_form_signal():
    assert 300 <= F._days("2025-02-01", "2026-01-31") <= 400
    assert F._FORM_SIGNAL["8-K"] == "material_event" and F._FORM_SIGNAL["4"] == "insider_trade"


@pytest.mark.live
def test_sec_financials_live():
    d = F.sec_financials("GitLab", ticker="GTLB")
    assert d["is_public"] and d["financials"]["revenue"]["form"] in F._ANNUAL_FORMS
    assert d["financials"]["revenue"]["value"] > 5e8        # annual revenue, not a quarter


@pytest.mark.live
def test_private_company_out_of_scope():
    d = F.sec_financials("Stripe")
    assert d["is_public"] is False and "note" in d          # honest out-of-scope, not a blank
