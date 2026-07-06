"""Lead-miner workbench engine (examples/leadgen/app.py) — the UI-free functions. Offline tests
cover the row shaping + no-website guards; live tests (mine/enrich) are marked and skipped by
default. The Streamlit UI is a thin shell over these; boot is smoke-tested separately."""
import importlib.util
from pathlib import Path

import pytest

# load under a unique name — the b2b example is also examples/*/app.py, so a bare `import app`
# collides in sys.modules across test files.
_spec = importlib.util.spec_from_file_location(
    "leadgen_app", Path(__file__).resolve().parents[1] / "examples" / "leadgen" / "app.py")
app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(app)


def test_flatten_shape():
    biz = {"name": "Acme Dental", "confidence": 0.789, "providers": ["overpass", "overture"],
           "phone": "6025551000", "website": "acme.com", "address": "1 Main", "category": "dentists"}
    row = app._flatten(biz)
    assert list(row.keys()) == app.LEAD_COLS
    assert row["confidence"] == 0.79 and row["sources"] == "overpass+overture"
    assert row["enriched"] is False and row["email"] == ""     # enrichment cols start empty


def test_enrich_guards_no_website():
    assert app.enrich_contacts({"website": ""}) == {"error": "no website"}
    assert app.enrich_tech({"name": "x"}) == {"error": "no website"}


@pytest.mark.live
def test_mine_leads_live():
    rows, cov = app.mine_leads("dentists", "Phoenix, AZ", sources=["overpass"], limit=20)
    assert rows and list(rows[0].keys()) == app.LEAD_COLS
    assert cov["counts"].get("overpass", 0) > 0
    assert all(0 <= r["confidence"] <= 1 for r in rows)


@pytest.mark.live
def test_enrich_tech_live():
    updates = app.enrich_tech({"website": "stripe.com"})
    assert updates["enriched"] is True and updates["modernness"]      # grade string present
