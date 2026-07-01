"""The evidence model + recipe layer — pure, deterministic (no network). Proves the clean-room
stance: core unions evidence + counts corroboration; recipes apply the CALLER's judgment, with
the persona-found bugs now expressed as visible knobs."""
from pith.evidence import Source, Fact, Coverage, aggregate
from pith import recipes


def test_aggregate_counts_corroboration_never_drops():
    # same phone seen on two pages + a third page's different number
    obs = [
        ("(316) 555-0142", "phone", Source("https://acme.com/contact", "tel")),
        ("(316) 555-0142", "phone", Source("https://acme.com/about", "text")),
        ("(405) 555-9999", "phone", Source("https://acme.com/blog", "text")),
    ]
    facts = aggregate(obs)
    assert len(facts) == 2                                  # nothing dropped, deduped by value
    top = facts[0]
    assert top.value == "(316) 555-0142" and top.corroboration == 2   # 2 distinct source URLs
    assert top.methods == ["tel", "text"]                  # provenance kept
    assert facts[1].corroboration == 1                     # the lone number survives too


def test_owner_email_recipe_is_caller_preference():
    facts = [
        Fact("info@acme.com", "email", [Source("https://acme.com", "text")], {"email_type": "role"}),
        Fact("jane@acme.com", "email", [Source("https://acme.com/team", "schema.org")], {"email_type": "person"}),
    ]
    # a sales rep prefers a person over a role mailbox — no accommodations@ surprise
    got = recipes.owner_email(facts, prefer=("owner", "person", "role"))
    assert got.value == "jane@acme.com"                    # returns the Fact, with provenance
    assert got.sources[0].method == "schema.org"
    # a support tool wants the role mailbox instead — same evidence, different intent
    assert recipes.owner_email(facts, prefer=("role",)).value == "info@acme.com"


def test_rank_phones_area_code_filter():
    facts = [
        Fact("(316) 555-0142", "phone", [Source("u1", "tel"), Source("u2", "text")]),
        Fact("(405) 555-9999", "phone", [Source("u3", "text")]),
        Fact("(913) 555-1111", "phone", [Source("u4", "text")]),
    ]
    # the caller knows the business is in 316 — filters the scrape noise (4 area codes -> 1)
    only316 = recipes.rank_phones(facts, area_code=316)
    assert [f.value for f in only316] == ["(316) 555-0142"]
    # without the filter: all, ranked by corroboration
    assert recipes.rank_phones(facts)[0].value == "(316) 555-0142"


def test_accept_identity_knobs_fix_the_persona_bugs():
    corr = [{
        "candidate_url": "https://github.com/beaulebens",
        "signals": [
            {"name": "BACKLINK", "source_url": "https://github.com/beaulebens"},   # self-reference!
            {"name": "BACKLINK", "source_url": "https://x.com/beaulebens"},        # real cross-link (x.com)
        ],
    }]
    # exclude_self drops the self-reference; alias_hosts keeps x.com == twitter as valid.
    # With only 1 independent signal left, min_signals=2 correctly REJECTS (no false ACCEPT).
    assert recipes.accept_identity(corr, min_signals=2, exclude_self=True) == []
    # caller who accepts a single independent signal gets it — their call, visible
    got = recipes.accept_identity(corr, min_signals=1, exclude_self=True)
    assert got[0]["count"] == 1 and got[0]["signals"][0]["source_url"] == "https://x.com/beaulebens"


def test_qualify_is_the_apps_icp():
    contact = {"grade": "D", "facts": [{"kind": "email"}, {"kind": "phone"}]}
    assert recipes.qualify(contact, require=("email",)) is True
    assert recipes.qualify(contact, require=("email", "social")) is False       # no social -> not qualified
    assert recipes.qualify(contact, require=("email",), max_grade="C") is True  # D is worse than C -> dated -> passes


def test_coverage_is_honest():
    cov = Coverage(checked=["a", "b", "c"], ok=["a"], failed=[{"url": "b", "error": "timeout"}], inconclusive=["c"])
    d = cov.as_dict()
    assert d["checked"] == 3 and d["inconclusive"] == ["c"] and d["failed"][0]["error"] == "timeout"
