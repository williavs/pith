"""Per-extractor precision/recall — every filter must keep the real thing AND drop the junk.
Each test names KEEP cases (recall: must not be cut) and DROP cases (precision: must not leak)."""
from pith.extract import emails, phones, socials, structured, meta, enrich, cfemails, _decode_cfemail


def _cf_encode(email, key=0x42):
    return f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in email)


def test_cfemail_decode_roundtrip():
    for e in ["owner@acmehvac.com", "jane.doe@small-biz.co.uk", "info@x.io"]:
        assert _decode_cfemail(_cf_encode(e)) == e


def test_cfemails_recovers_from_html():
    html = f'<a class="__cf_email__" data-cfemail="{_cf_encode("boss@hvac.com", 0x1f)}">[email&#160;protected]</a>'
    assert cfemails(html) == ["boss@hvac.com"]


def test_cfemail_rejects_garbage():
    assert _decode_cfemail("zzzz") == "" and _decode_cfemail("00") == ""


def test_enrich_recovers_cloudflare_hidden_email():
    # the page shows NO plaintext email — only the cloudflare-obfuscated one
    html = f'<span>Email us:</span><a class="__cf_email__" data-cfemail="{_cf_encode("owner@shop.com")}">[email protected]</a>'
    d = enrich("", html)
    assert "owner@shop.com" in d["emails"]


def test_entity_encoded_email_recovered():
    assert "john@acme.com" in emails("reach john&#64;acme&#46;com anytime")  # &#64;=@ &#46;=.


def test_cfemail_from_clickable_link_fragment():
    from pith.extract import cfemails
    html = f'<a href="/cdn-cgi/l/email-protection#{_cf_encode("boss@hvac.com", 0x2a)}">email</a>'
    assert cfemails(html) == ["boss@hvac.com"]


def test_atdot_bracketed_only():
    from pith.extract import atdot_emails
    assert atdot_emails("sales [at] acme [dot] com") == ["sales@acme.com"]
    assert atdot_emails("bob (at) foo (dot) org") == ["bob@foo.org"]
    # bare lowercase 'at'/'dot' in prose must NOT fabricate an email
    assert atdot_emails("meet me at the dot for lunch") == []
    assert atdot_emails("look at that dotcom bubble") == []


def test_phone_normalizer_recovers_obfuscated():
    # nbsp, unicode hyphen (U+2011), fullwidth digits — all should still yield the phone
    assert phones("Call 415 555 2671") == ["(415) 555-2671"]
    assert phones("Call 415‑555‑2671") == ["(415) 555-2671"]  # U+2011 hyphens


def test_structured_drops_review_author_keeps_owner():
    html = ('<script type="application/ld+json">{"@type":"Product","name":"AC",'
            '"review":{"@type":"Review","author":{"@type":"Person","name":"Karen W"}}}</script>'
            '<script type="application/ld+json">{"@type":"Organization","name":"Acme",'
            '"founder":{"@type":"Person","name":"Jeff Smith","jobTitle":"Owner"}}</script>')
    names = [e.get("name") for e in structured(html)]
    assert "Karen W" not in names          # review author -> dropped (precision)
    assert "Jeff Smith" in names           # founder -> kept


def test_address_assembly_and_gate():
    from pith.extract import addresses
    html = ('<script type="application/ld+json">{"@type":"LocalBusiness","name":"Acme HVAC",'
            '"address":{"@type":"PostalAddress","streetAddress":"123 Main St",'
            '"addressLocality":"Columbus","addressRegion":"OH","postalCode":"43004"}}</script>')
    assert addresses(html) == ["123 Main St, Columbus OH 43004"]
    # zip-only must NOT emit (>=2 component gate)
    thin = '<script type="application/ld+json">{"@type":"Organization","name":"X","address":{"@type":"PostalAddress","postalCode":"43004"}}</script>'
    assert addresses(thin) == []


# ---- emails: keep real contacts, drop trackers/placeholders/asset filenames ----

def test_emails_keeps_real():
    text = "reach macinnis@rippling.com or john.doe@acme.co.uk, sarah+sales@big.io, a_b-c@sub.domain.io"
    got = emails(text)
    for e in ["macinnis@rippling.com", "john.doe@acme.co.uk", "sarah+sales@big.io", "a_b-c@sub.domain.io"]:
        assert e in got, f"recall miss: {e}"


def test_emails_drops_junk():
    junk = ("logo@2x.png hero@3x.webp your@email.com name@example.com user@domain.com "
            "abc@sentry.io dsn@o123.sentry.wixpress.com test@test.com icon@company.svg")
    assert emails(junk) == [], f"precision leak: {emails(junk)}"


# ---- phones: only explicit tel: links (free-text numbers are tracking-ID noise) ----

def test_phones_canonicalize_and_dedup():
    # same number, many formats -> ONE canonical (415) 555-1234; count/corroboration is the
    # caller's job (waterfall), the extractor just normalizes format.
    html = '<a href="tel:+14155551234">call</a> <a href="tel:415-555-1234">or</a> 415.555.1234'
    assert phones(html) == ["(415) 555-1234"]


def test_phones_keeps_formatted_text_numbers():
    # phones shown as plain text (no tel: link) — the common case trafilatura strips
    txt = "Call us at (614) 836-8188 or 937-776-4851, toll free +1 330.764.1011"
    got = phones(txt)
    for p in ["(614) 836-8188", "(937) 776-4851", "(330) 764-1011"]:  # canonicalized
        assert p in got, f"recall miss: {p} in {got}"


def test_phones_drops_contiguous_and_junk():
    # tracking IDs / contiguous digit runs / dates / versions must NOT match (separators required)
    junk = "session 0060833459 order 1603580557 date 2026-07-01 version 1.234.567 id 123456789"
    assert phones(junk) == [], f"precision leak: {phones(junk)}"


# ---- socials: keep profile URLs, drop share/intent/nav UI links ----

def test_socials_keeps_profiles():
    html = ("https://www.linkedin.com/in/macinnis https://linkedin.com/company/rippling "
            "https://twitter.com/rippling https://github.com/torvalds https://instagram.com/nasa")
    got = socials(html)
    for u in ["https://www.linkedin.com/in/macinnis", "https://linkedin.com/company/rippling",
              "https://twitter.com/rippling", "https://github.com/torvalds"]:
        assert u in got, f"recall miss: {u}"


def test_socials_drops_ui_links():
    html = ("https://twitter.com/share?url=x https://twitter.com/intent/tweet https://x.com/home "
            "https://www.facebook.com/sharer/sharer.php https://twitter.com/login")
    assert socials(html) == [], f"precision leak: {socials(html)}"


# ---- structured (JSON-LD): keep Person/Organization, skip other types + malformed ----

def test_structured_keeps_person_and_org():
    html = '''
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Person","name":"Matt MacInnis",
       "jobTitle":"Chief Product Officer","sameAs":["https://linkedin.com/in/macinnis"]}
    </script>
    <script type="application/ld+json">
      {"@graph":[{"@type":"Organization","name":"Rippling","telephone":"+1-888-000-0000"}]}
    </script>'''
    st = structured(html)
    by_type = {e["@type"]: e for e in st}
    assert by_type["Person"]["name"] == "Matt MacInnis"
    assert by_type["Person"]["jobTitle"] == "Chief Product Officer"
    assert by_type["Organization"]["name"] == "Rippling"       # @graph unwrapped
    assert by_type["Organization"]["telephone"] == "+1-888-000-0000"


def test_structured_skips_noise_and_malformed():
    html = ('<script type="application/ld+json">{"@type":"WebSite","name":"Rippling"}</script>'
            '<script type="application/ld+json">{"@type":"BreadcrumbList","name":"x"}</script>'
            '<script type="application/ld+json">{not valid json,,,}</script>')
    assert structured(html) == [], f"precision leak: {structured(html)}"


# ---- meta: OpenGraph + author ----

def test_meta_extracts_og_and_author():
    html = ('<meta property="og:title" content="Matt at Rippling">'
            '<meta property="og:description" content="CPO">'
            '<meta name="author" content="Matt MacInnis">')
    m = meta(html)
    assert m["title"] == "Matt at Rippling" and m["description"] == "CPO" and m["author"] == "Matt MacInnis"


# ---- enrich: one call folds schema.org telephone into phones, dedups ----

def test_enrich_folds_schema_phone():
    html = '<script type="application/ld+json">{"@type":"Organization","name":"A","telephone":"+1-800-555-0100"}</script>'
    d = enrich("body text", html)
    assert "+1-800-555-0100" in d["phones"]
    assert d["structured"][0]["name"] == "A"
