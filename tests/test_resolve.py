"""Identity corroboration scoring — the gate that turns handle-existence into 'is it them'."""
from pith.resolve import Target, score
from pith.core import Result

_T = Target(name="Matt MacInnis", company="Rippling", website="https://rippling.com",
            anchors={"https://linkedin.com/in/macinnis"}, emails={"matt@rippling.com"})


def test_backlink_is_decisive():
    r = Result(url="https://github.com/m", socials=["https://www.linkedin.com/in/macinnis/"])
    s = score(_T, r)
    assert "BACKLINK" in s["signals"] and s["verdict"] == "ACCEPT"   # +2 alone


def test_name_plus_company_domain_accepts():
    r = Result(url="https://x.com/m", structured=[{"@type": "Person", "name": "Matt MacInnis"}],
               socials=["https://rippling.com/team"])
    s = score(_T, r)
    assert {"FULL-NAME", "COMPANY-DOMAIN"} <= set(s["signals"]) and s["verdict"] == "ACCEPT"


def test_name_only_is_review():
    r = Result(url="https://medium.com/m", structured=[{"@type": "Person", "name": "Matt MacInnis"}])
    assert score(_T, r)["verdict"] == "REVIEW"                       # C=1, not enough alone


def test_wrong_person_rejected():
    r = Result(url="https://chaturbate.com/matt", structured=[{"@type": "Person", "name": "Someone Else"}])
    assert score(_T, r)["verdict"] == "REJECT"                      # handle collision -> dropped


def test_shared_contact_signal():
    r = Result(url="https://about.me/m", emails=["matt@rippling.com"])
    s = score(_T, r)
    # shared email + the company domain it implies -> ACCEPT
    assert "SHARED-CONTACT" in s["signals"]


def test_resolve_person_crosslink_boost(monkeypatch):
    from pith import resolve
    hits = [
        {"site": "Medium", "url": "https://medium.com/@m", "value": "high", "recency": True,
         "kind": "psychographic", "verdict": "REVIEW", "confidence": 0.33, "signals": ["FULL-NAME"], "links": []},
        {"site": "GitHub", "url": "https://github.com/m", "value": "high", "recency": True,
         "kind": "firmographic", "verdict": "ACCEPT", "confidence": 0.67, "signals": ["BACKLINK"],
         "links": ["medium.com/@m"]},   # GitHub links to the Medium profile -> corroborates it
    ]
    monkeypatch.setattr(resolve, "resolve_profiles", lambda *a, **k: hits)
    from pith.resolve import resolve_person, Target
    p = resolve_person("m", Target())
    verdicts = {h["site"]: h["verdict"] for h in p["profiles"]}
    assert verdicts.get("Medium") == "ACCEPT"          # boosted via cross-link
    assert p["confidence"] >= 0.4 and "GitHub" in p["best_channels"]
