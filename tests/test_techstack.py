"""Website tech + modernness analysis — deterministic, offline (synthetic HTML)."""
from pith.techstack import analyze

_VIEWPORT = '<meta name="viewport" content="width=device-width, initial-scale=1">'


def test_modern_custom_site_grades_high():
    html = f'<html><head>{_VIEWPORT}</head><body><script src="/_next/static/x.js"></script>__NEXT_DATA__</body></html>'
    a = analyze(html, "https://acme.com")
    assert a["framework"] == "Next.js"
    assert a["builder"] == "custom (Next.js)"
    assert a["hosted_builder"] is False
    assert a["responsive"] and a["https"]
    assert a["modernness_grade"] == "A"


def test_dated_non_responsive_site_grades_low():
    # no viewport, table layout, font tags, http -> strong website-services prospect
    html = "<html><body><table></table><table></table><table></table><font>old</font>© 2013</body></html>"
    a = analyze(html, "http://oldbiz.com")
    assert not a["responsive"]
    assert "not-responsive" in a["dated_signals"]
    assert a["modernness_grade"] in ("D", "F")     # never reads as modern
    assert a["modernness_score"] <= 55


def test_hosted_builder_detected():
    html = f'<html><head>{_VIEWPORT}</head><body><script src="https://static.wixstatic.com/x.js"></script></body></html>'
    a = analyze(html, "https://mybiz.com")
    assert a["builder"] == "Wix"
    assert a["hosted_builder"] is True             # paying a DIY service -> switch pitch


def test_wordpress_is_not_hosted_builder():
    html = f'<html><head>{_VIEWPORT}</head><body>wp-content/themes/x wp-json</body></html>'
    a = analyze(html, "https://shop.com")
    assert a["builder"] == "WordPress" and a["hosted_builder"] is False


def test_non_responsive_hard_caps_even_with_modern_framework():
    # a JS-framework site that somehow lacks viewport still can't be an A
    html = '<html><body>__NEXT_DATA__ /_next/</body></html>'
    a = analyze(html, "https://x.com")
    assert not a["responsive"] and a["modernness_score"] <= 55


def test_empty_html_is_unknown_not_crash():
    a = analyze("", "")
    assert a["builder"] == "unknown" and a["framework"] is None
