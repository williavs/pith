"""pith.leads waterfall — the cross-source clustering + field aggregation + confidence blend.
All offline (no network): feed RawBiz from fake providers, assert the merge behaves. Live
provider hits are in test_live.py."""
from pith import leads
from pith.leads import RawBiz, _cluster, _merge_cluster, _norm_name, _norm_phone, _taxon, _WEIGHTS, Business


def test_normalizers():
    assert _norm_name("Joe's Plumbing, LLC") == "joe s plumbing"
    assert _norm_name("The Corner Cafe Inc") == "corner cafe"
    assert _norm_phone("+1 (602) 555-1212") == "6025551212"
    assert _norm_phone("602.555.1212") == "6025551212"


def test_cluster_matches_by_phone_and_name_geo():
    a = RawBiz("Joe's Plumbing LLC", "overpass", 33.45, -112.07, phone="(602) 555-1212")
    b = RawBiz("Joe's Plumbing", "overture", 33.4501, -112.0701, website="joesplumbing.com")  # name+geo
    c = RawBiz("Something Else", "yelp", 33.45, -112.07, phone="602-555-1212")                # shared phone
    d = RawBiz("Faraway Diner", "overpass", 40.0, -74.0)
    clusters = _cluster([a, b, c, d])
    sizes = sorted(len(cl) for cl in clusters)
    assert sizes == [1, 3]           # a+b (name/geo) + c (phone==a) merge; d alone


def test_merge_corroboration_and_confidence():
    a = RawBiz("Acme Dental", "overpass", 33.4, -112.0, phone="6025551000", website="http://acmedental.com")
    b = RawBiz("Acme Dental", "overture", 33.4, -112.0, website="https://www.acmedental.com/",
               email="hi@acmedental.com", confidence=0.9)
    biz = _merge_cluster([a, b], _WEIGHTS)
    assert set(biz.providers) == {"overpass", "overture"}
    assert biz.fields["website"].corroboration == 2      # both attest the site (normalized equal)
    assert biz.fields["phone"].corroboration == 1        # only overpass had it
    assert biz._best("email") == "hi@acmedental.com"     # single-source field still surfaced, not dropped
    assert biz.confidence > 0.6                          # two independent sources => confident


def test_single_source_lower_confidence():
    solo = _merge_cluster([RawBiz("Lonely LLC", "overpass", 33.4, -112.0)], _WEIGHTS)
    both = _merge_cluster([RawBiz("Pair", "overpass", 33.4, -112.0),
                           RawBiz("Pair", "overture", 33.4, -112.0)], _WEIGHTS)
    assert solo.confidence < both.confidence             # corroboration must raise confidence


def test_overture_own_confidence_lifts_single_source():
    low = _merge_cluster([RawBiz("X", "overture", 33.4, -112.0, confidence=0.1)], _WEIGHTS)
    high = _merge_cluster([RawBiz("Y", "overture", 33.4, -112.0, confidence=0.95)], _WEIGHTS)
    assert high.confidence > low.confidence              # provider's own score is folded in


def test_evidence_shape_in_as_dict():
    biz = _merge_cluster([RawBiz("Z Co", "overpass", 33.4, -112.0, phone="6025550000"),
                          RawBiz("Z Co", "overture", 33.4, -112.0, phone="6025550000", confidence=0.8)], _WEIGHTS)
    d = biz.as_dict()
    assert d["corroboration"] == 2 and d["providers"] == ["overpass", "overture"]
    assert d["evidence"]["phone"]["corroboration"] == 2   # evidence retained per field
    assert 0.0 <= d["confidence"] <= 1.0


def test_taxonomy_mapping_and_fallback():
    assert "amenity=dentist" in _taxon("dentists").osm
    assert "dentist" in _taxon("Dentist").overture        # singular + case handled
    unknown = _taxon("artisanal cheese caves")
    assert unknown.osm == () and unknown.term == "artisanal cheese caves"   # free-text fallback


def test_registry_has_keyless_providers():
    assert "overpass" in leads.PROVIDERS and "overture" in leads.PROVIDERS
    assert leads.PROVIDERS["overpass"].available({}) is True          # live, no deps
    assert leads.PROVIDERS["overpass"].needs_key is False


def test_register_custom_provider():
    class Fake:
        name = "fake"; needs_key = False; key_env = ""; weight = 0.6
        update_frequency = "n/a"; reliability = "n/a"; license = "n/a"
        def available(self, config): return True
        def search(self, spec): return []
    leads.register(Fake())
    try:
        assert "fake" in leads.PROVIDERS and leads._WEIGHTS["fake"] == 0.6
    finally:
        leads.PROVIDERS.pop("fake", None); leads._WEIGHTS.pop("fake", None)
