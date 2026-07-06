"""B2B account-intelligence engine (examples/b2b/app.py) — the UI-free helpers. Offline: target
parsing, news-signal rollup, lens read, funding string. Live (marked): a full account dossier."""
import importlib.util
from pathlib import Path

import pytest

# unique module name — both example apps are examples/*/app.py (see test_leadgen_app.py).
_spec = importlib.util.spec_from_file_location(
    "b2b_app", Path(__file__).resolve().parents[1] / "examples" / "b2b" / "app.py")
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def test_parse_target():
    assert app._parse_target("ramp.com") == ("Ramp", "ramp.com")
    assert app._parse_target("Vercel,vercel.com") == ("Vercel", "vercel.com")
    assert app._parse_target("https://www.notion.so/") == ("Notion", "notion.so")
    assert app._parse_target("acme-corp.io")[0] == "Acme Corp"     # SLD -> title-cased name


def test_news_signals_rollup():
    items = [{"signal": "funding"}, {"signal": "funding"}, {"signal": "ai"}, {"signal": "news"}, {"signal": None}]
    s = app._news_signals(items)
    assert "funding:2" in s and "ai:1" in s and "news" not in s     # 'news' (generic) excluded


def test_funding_str_prefers_largest_and_public():
    priv = {"kind": "private_or_other", "funding": {"raises": [
        {"total_sold": 39e6, "filed": "2014-04-01"}, {"total_sold": 300e6, "filed": "2021-01-01"}]}}
    assert "300M" in app._funding_str(priv)                         # largest, not oldest
    pub = {"kind": "us_public", "financials": {"financials": {"revenue": {"value": 5.5e8}}}}
    assert app._funding_str(pub).startswith("public")


def test_lens_read_differs_by_lens():
    d = {"employees": "500", "open_roles": 40, "funding": "raised $150M", "tech": "Next.js",
         "signals": "ai:68 product:10"}
    payroll = app._lens_read(d, "payroll")
    ai = app._lens_read(d, "ai_services")
    assert "employees" in payroll and "ai news: 68" in ai and "tech" in ai


def test_no_people_column():
    assert "people" not in app.ACCOUNT_COLS      # B2B decision-makers are LinkedIn/paid, not here


@pytest.mark.live
def test_enrich_account_live():
    d = app.enrich_account("vercel.com", lens="ai_services")
    assert d["domain"] == "vercel.com" and d["enriched"] is True
    assert d["open_roles"] > 0 and d["tech"]           # hiring + tech are the reliable signals
    assert list(d.keys()) == app.ACCOUNT_COLS
