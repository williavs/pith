"""Phone intelligence — validity, region, line type, carrier, E.164 — via Google's
libphonenumber (the `phonenumbers` port). Fully OFFLINE and deterministic: no lookups, no
network, no per-query cost. Upgrades any number pith already extracts.

Needs the optional extra:  pip install 'pith[osint]'
"""
from __future__ import annotations


def _line_type(t) -> str:
    import phonenumbers
    return {
        phonenumbers.PhoneNumberType.MOBILE: "mobile",
        phonenumbers.PhoneNumberType.FIXED_LINE: "fixed_line",
        phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE: "fixed_or_mobile",
        phonenumbers.PhoneNumberType.TOLL_FREE: "toll_free",
        phonenumbers.PhoneNumberType.VOIP: "voip",
        phonenumbers.PhoneNumberType.PREMIUM_RATE: "premium_rate",
        phonenumbers.PhoneNumberType.SHARED_COST: "shared_cost",
        phonenumbers.PhoneNumberType.PERSONAL_NUMBER: "personal",
        phonenumbers.PhoneNumberType.PAGER: "pager",
        phonenumbers.PhoneNumberType.UAN: "uan",
        phonenumbers.PhoneNumberType.VOICEMAIL: "voicemail",
    }.get(t, "unknown")


def phone_intel(number: str, region: str | None = None) -> dict:
    """A phone string -> {valid, e164, country_code, region, location, carrier, line_type}.

    `region` is a 2-letter code (US, GB, IN...) used to parse NATIONAL-format numbers. If it's
    omitted and the number has no leading '+', pith assumes US (its NANP default) and flags
    assumed_region — pass region explicitly for other countries."""
    try:
        import phonenumbers
        from phonenumbers import geocoder, carrier
    except ImportError as e:
        raise RuntimeError("phone intelligence needs: pip install 'pith[osint]'") from e

    raw = (number or "").strip()
    assumed = False
    if region is None and not raw.startswith("+"):
        region, assumed = "US", True          # pith's NANP default; caller can override
    try:
        n = phonenumbers.parse(raw, region)
    except phonenumbers.NumberParseException as e:
        return {"input": number, "valid": False, "error": str(e)}

    valid = phonenumbers.is_valid_number(n)
    out = {
        "input": number,
        "valid": valid,
        "possible": phonenumbers.is_possible_number(n),
        "e164": phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164),
        "international": phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
        "country_code": n.country_code,
        "region": phonenumbers.region_code_for_number(n),
        "location": geocoder.description_for_number(n, "en") or None,
        "carrier": carrier.name_for_number(n, "en") or None,     # original network only (ported = blank)
        "line_type": _line_type(phonenumbers.number_type(n)),
    }
    if assumed:
        out["assumed_region"] = "US"
    return out
