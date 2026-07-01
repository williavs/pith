"""Per-extractor precision/recall — every filter must keep the real thing AND drop the junk.
Each test names KEEP cases (recall: must not be cut) and DROP cases (precision: must not leak)."""
from pith.extract import emails, phones, socials, structured, meta, enrich


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

def test_phones_keeps_tel_links():
    html = '<a href="tel:+14155551234">call</a> <a href="tel:415-555-1234">or</a>'
    got = phones(html)
    assert "+14155551234" in got and "415-555-1234" in got


def test_phones_keeps_formatted_text_numbers():
    # phones shown as plain text (no tel: link) — the common case trafilatura strips
    txt = "Call us at (614) 836-8188 or 937-776-4851, toll free +1 330.764.1011"
    got = phones(txt)
    for p in ["(614) 836-8188", "937-776-4851"]:
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
