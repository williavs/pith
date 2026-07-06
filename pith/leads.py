"""Multi-source local-business discovery — keyless-first, key-optional, cross-source validated.

pith's core stance (evidence, not answers) applied to business data: every provider that
attests a business is a Source; every field (name/phone/website/email/address) becomes a
Fact whose corroboration = how many DISTINCT providers agree. A business confirmed by three
independent datasets is more trustworthy than one seen once — and pith shows you that, it
doesn't hide it behind a scalar.

    Provider   — a source adapter (overpass/overture/fsq_open keyless; yelp/google/fsq_api keyed).
    Business   — one merged record; each field carries its evidence.Fact (value + sources + corrob).
    waterfall  — cluster raw records across providers by name+geo, then aggregate each field.
    find_businesses(category, location, ...) — the one call; abstracts geocode/taxonomy/merge away.

Keyless out of the box (OSM/Overpass live; Overture + Foursquare-Open bulk via `pith[places]`).
Keyed providers light up when a free key is configured (env or the `config` arg) — never required.

Design contract for a Provider (so new sources drop in without touching the engine):
    class XProvider:
        name, needs_key, key_env, update_frequency, reliability, license, weight   # metadata
        def available(self, config) -> bool: ...                 # dep present / key set?
        def search(self, spec: SearchSpec) -> list[RawBiz]: ...  # do the query, normalize rows
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Optional

from .evidence import Fact, Source, aggregate

_UA = os.environ.get("PITH_LEADS_UA", "pith-leads (https://github.com/williavs/pith)")
_GEO_TTL = 86400
_geo_cache: dict[str, tuple] = {}


# ---------------------------------------------------------------------------
# shared HTTP + geocode
# ---------------------------------------------------------------------------

def _get(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 60) -> bytes:
    h = {"User-Agent": _UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    return urllib.request.urlopen(req, timeout=timeout).read()


def geocode(location: str) -> dict:
    """Location string -> {lat, lon, bbox:(s,w,n,e), display}. Keyless via OSM Nominatim.
    Nominatim asks for <=1 req/s and a real UA; results are cached per process."""
    key = location.strip().lower()
    hit = _geo_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _GEO_TTL:
        return hit[1]
    q = urllib.parse.urlencode({"q": location, "format": "json", "limit": 1})
    rows = json.loads(_get(f"https://nominatim.openstreetmap.org/search?{q}", timeout=30))
    if not rows:
        raise ValueError(f"could not geocode location: {location!r}")
    r = rows[0]
    s, n, w, e = (float(x) for x in r["boundingbox"])   # nominatim order: south, north, west, east
    out = {"lat": float(r["lat"]), "lon": float(r["lon"]), "bbox": (s, w, n, e),
           "display": r.get("display_name", location)}
    _geo_cache[key] = (time.monotonic(), out)
    return out


def _bbox_from_radius(lat: float, lon: float, radius_km: float) -> tuple:
    """(south, west, north, east) box around a point. Rough: 1 deg lat ~111km."""
    import math
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


# ---------------------------------------------------------------------------
# category taxonomy — canonical niche -> each source's own vocabulary
# ---------------------------------------------------------------------------
# Only the mapping lives here; providers translate the relevant slice. Unmapped categories
# fall back to free-text search where a provider supports it (yelp/google/overpass name~).

@dataclass(frozen=True)
class Taxon:
    osm: tuple = ()          # OSM tag filters, e.g. ('amenity=dentist','healthcare=dentist')
    overture: tuple = ()     # Overture category primary values
    fsq: tuple = ()          # Foursquare category name substrings
    term: str = ""           # free-text term for yelp/google/name search (defaults to the key)


_CATEGORIES: dict[str, Taxon] = {
    "restaurants":  Taxon(("amenity=restaurant",), ("restaurant", "eat_and_drink"), ("Restaurant",), "restaurants"),
    "cafes":        Taxon(("amenity=cafe",), ("cafe", "coffee_shop"), ("Café", "Coffee"), "coffee"),
    "bars":         Taxon(("amenity=bar", "amenity=pub"), ("bar", "pub"), ("Bar",), "bars"),
    "dentists":     Taxon(("amenity=dentist", "healthcare=dentist"), ("dentist",), ("Dentist",), "dentists"),
    "doctors":      Taxon(("amenity=doctors", "healthcare=doctor"), ("physician", "doctor"), ("Doctor",), "doctors"),
    "lawyers":      Taxon(("office=lawyer",), ("lawyer", "legal_service"), ("Lawyer", "Legal"), "lawyers"),
    "accountants":  Taxon(("office=accountant",), ("accounting", "accountant"), ("Accountant",), "accountants"),
    "realtors":     Taxon(("office=estate_agent",), ("real_estate", "real_estate_agent"), ("Real Estate",), "real estate agents"),
    "plumbers":     Taxon(("craft=plumber", "shop=plumber"), ("plumber", "plumbing_service"), ("Plumber",), "plumbers"),
    "roofers":      Taxon(("craft=roofer",), ("roofer", "roofing_service"), ("Roofing",), "roofing contractors"),
    "electricians": Taxon(("craft=electrician",), ("electrician",), ("Electrician",), "electricians"),
    "hvac":         Taxon(("craft=hvac", "trade=hvac"), ("hvac", "heating_and_air"), ("HVAC",), "hvac contractors"),
    "contractors":  Taxon(("craft=builder", "office=construction_company"), ("contractor", "construction"), ("Contractor",), "general contractors"),
    "landscapers":  Taxon(("shop=garden_centre", "craft=gardener"), ("landscaping", "landscaper"), ("Landscap",), "landscaping"),
    "gyms":         Taxon(("leisure=fitness_centre",), ("gym", "fitness"), ("Gym", "Fitness"), "gyms"),
    "salons":       Taxon(("shop=hairdresser", "shop=beauty"), ("hair_salon", "beauty_salon"), ("Salon", "Hair"), "hair salons"),
    "auto_repair":  Taxon(("shop=car_repair",), ("automotive_repair", "auto_repair"), ("Auto", "Mechanic"), "auto repair"),
    "car_dealers":  Taxon(("shop=car",), ("car_dealer", "automotive_dealer"), ("Car Dealer",), "car dealerships"),
    "insurance":    Taxon(("office=insurance",), ("insurance", "insurance_agency"), ("Insurance",), "insurance agents"),
    "veterinarians": Taxon(("amenity=veterinary",), ("veterinarian", "veterinary"), ("Veterinar",), "veterinarians"),
    "pharmacies":   Taxon(("amenity=pharmacy",), ("pharmacy",), ("Pharmacy",), "pharmacies"),
    "hotels":       Taxon(("tourism=hotel",), ("hotel", "lodging"), ("Hotel",), "hotels"),
    "gas_stations": Taxon(("amenity=fuel",), ("gas_station",), ("Gas Station",), "gas stations"),
    "banks":        Taxon(("amenity=bank",), ("bank",), ("Bank",), "banks"),
    "florists":     Taxon(("shop=florist",), ("florist",), ("Florist",), "florists"),
    "bakeries":     Taxon(("shop=bakery",), ("bakery",), ("Bakery",), "bakeries"),
    "pet_grooming": Taxon(("shop=pet_grooming", "shop=pet"), ("pet_service", "pet_groomer"), ("Pet",), "pet grooming"),
    "cleaners":     Taxon(("shop=dry_cleaning", "shop=laundry"), ("dry_cleaning", "laundry_service"), ("Cleaner", "Laundry"), "cleaning services"),
    "childcare":    Taxon(("amenity=childcare", "amenity=kindergarten"), ("childcare", "daycare"), ("Daycare", "Child"), "daycare"),
}


def _taxon(category: str) -> Taxon:
    key = category.strip().lower().replace(" ", "_").replace("-", "_")
    if key in _CATEGORIES:
        return _CATEGORIES[key]
    # singular/plural nudge
    for k in (key + "s", key.rstrip("s")):
        if k in _CATEGORIES:
            return _CATEGORIES[k]
    return Taxon(term=category)     # free-text fallback (yelp/google/name search still work)


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------

@dataclass
class RawBiz:
    """One business as a single provider saw it — before cross-source merge."""
    name: str
    provider: str
    lat: Optional[float] = None
    lon: Optional[float] = None
    phone: str = ""
    website: str = ""
    email: str = ""
    address: str = ""
    socials: list[str] = field(default_factory=list)
    category: str = ""
    confidence: Optional[float] = None      # provider's own score (Overture has one)
    last_seen: str = ""                      # provider freshness stamp if any
    url: str = ""                            # a link back to the provider's record


@dataclass
class Business:
    """A merged business. Each field is an evidence.Fact (value + which providers + corroboration).
    `confidence` is a transparent 0-1 blend of corroboration x provider reliability — shown, not hidden."""
    name: str
    lat: Optional[float]
    lon: Optional[float]
    fields: dict = field(default_factory=dict)       # field_name -> best Fact
    providers: list[str] = field(default_factory=list)
    confidence: float = 0.0
    address: str = ""
    category: str = ""

    def _best(self, k: str) -> str:
        f = self.fields.get(k)
        return f.value if f else ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "phone": self._best("phone"),
            "website": self._best("website"),
            "email": self._best("email"),
            "address": self.address or self._best("address"),
            "socials": [f.value for f in self.fields.get("_socials", [])] if isinstance(self.fields.get("_socials"), list) else [],
            "category": self.category,
            "lat": self.lat, "lon": self.lon,
            "confidence": round(self.confidence, 3),
            "providers": self.providers,
            "corroboration": len(self.providers),
            "evidence": {k: v.as_dict() for k, v in self.fields.items() if isinstance(v, Fact)},
        }


@dataclass
class SearchSpec:
    category: str
    taxon: Taxon
    location: str
    geo: dict                 # geocode() output
    bbox: tuple               # (south, west, north, east) — radius-narrowed if requested
    limit: int
    config: dict


# ---------------------------------------------------------------------------
# waterfall — cluster raw records across providers, aggregate each field
# ---------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    s = re.sub(r"\b(llc|inc|co|corp|ltd|the)\b", " ", s)   # legal/filler words only as whole words
    return re.sub(r"\s+", " ", s).strip()


def _norm_phone(s: str) -> str:
    d = re.sub(r"\D", "", s or "")
    return d[-10:] if len(d) >= 10 else d


def _norm_site(s: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", (s or "").lower()).rstrip("/")


def _close(a: RawBiz, b: RawBiz) -> bool:
    """Same business? name match + geographic proximity (~150m), or a shared phone/site."""
    if a.phone and b.phone and _norm_phone(a.phone) == _norm_phone(b.phone):
        return True
    if a.website and b.website and _norm_site(a.website) == _norm_site(b.website):
        return True
    na, nb = _norm_name(a.name), _norm_name(b.name)
    if not na or na != nb:
        return False
    if a.lat is None or b.lat is None:
        return True                      # same name, no coords to contradict
    return abs(a.lat - b.lat) < 0.0015 and abs(a.lon - b.lon) < 0.0015


def _cluster(raws: list[RawBiz]) -> list[list[RawBiz]]:
    """Greedy single-link clustering. Fine for the hundreds-per-query scale (ponytail: O(n^2),
    swap for a spatial grid index if a query ever returns >5k rows)."""
    clusters: list[list[RawBiz]] = []
    for r in raws:
        for c in clusters:
            if any(_close(r, m) for m in c):
                c.append(r)
                break
        else:
            clusters.append([r])
    return clusters


# provider reliability weights feed the confidence blend (see PROVIDERS metadata below)
def _merge_cluster(cluster: list[RawBiz], weights: dict) -> Business:
    obs_by_field: dict[str, list] = {"name": [], "phone": [], "website": [], "email": [], "address": []}
    socials_obs = []
    lats = [r.lat for r in cluster if r.lat is not None]
    lons = [r.lon for r in cluster if r.lon is not None]
    for r in cluster:
        src = Source(url=r.url or f"{r.provider}:{_norm_name(r.name)}", method=r.provider)
        if r.name:    obs_by_field["name"].append((r.name, "name", src))
        if r.phone:   obs_by_field["phone"].append((r.phone, "phone", src))
        if r.website: obs_by_field["website"].append((_norm_site(r.website), "website", src, {"raw": r.website}))
        if r.email:   obs_by_field["email"].append((r.email, "email", src))
        if r.address: obs_by_field["address"].append((r.address, "address", src))
        for s in r.socials:
            socials_obs.append((s, "social", src))
    fields: dict = {}
    for fname, obs in obs_by_field.items():
        facts = aggregate(obs)
        if facts:
            fields[fname] = facts[0]        # highest-corroboration value; evidence retained on the Fact
    if socials_obs:
        fields["_socials"] = aggregate(socials_obs)
    providers = sorted({r.provider for r in cluster})
    # confidence: reliability-weighted corroboration, dampened, plus a nudge from Overture's own score
    w = sum(weights.get(p, 0.5) for p in providers)
    conf = 1 - (1 / (1 + w))                # 1 provider(w.5)->.33, 2 strong->~.7, 3+->.8+
    ovt = next((r.confidence for r in cluster if r.provider == "overture" and r.confidence), None)
    if ovt is not None:
        conf = max(conf, 0.5 * conf + 0.5 * ovt)
    name_fact = fields.get("name")
    return Business(
        name=name_fact.value if name_fact else cluster[0].name,
        lat=sum(lats) / len(lats) if lats else None,
        lon=sum(lons) / len(lons) if lons else None,
        fields=fields, providers=providers, confidence=conf,
        address=fields["address"].value if "address" in fields else "",
        category=next((r.category for r in cluster if r.category), ""),
    )


# ---------------------------------------------------------------------------
# providers
# ---------------------------------------------------------------------------

class OverpassProvider:
    name = "overpass"
    needs_key = False
    key_env = ""
    update_frequency = "continuous (crowdsourced; minute-level edits, no SLA)"
    reliability = "existence/location strong; contact tags ~30% present; trades thinner than storefronts"
    license = "ODbL (attribution + share-alike)"
    weight = 0.7
    endpoint = os.environ.get("PITH_OVERPASS_URL", "https://overpass-api.de/api/interpreter")

    def available(self, config) -> bool:
        return True

    def search(self, spec: SearchSpec) -> list[RawBiz]:
        s, w, n, e = spec.bbox
        tags = spec.taxon.osm or (f'name~"{spec.taxon.term}",i',)   # name regex fallback
        parts = []
        for t in tags:
            if "=" in t:
                k, v = t.split("=", 1)
                parts.append(f'nwr["{k}"="{v}"]({s},{w},{n},{e});')
            else:
                parts.append(f'nwr[{t}]({s},{w},{n},{e});')
        q = f"[out:json][timeout:50];({''.join(parts)});out center tags meta {spec.limit * 3};"
        data = json.loads(_get(self.endpoint, urllib.parse.urlencode({"data": q}).encode(), timeout=90))
        out = []
        for el in data.get("elements", []):
            t = el.get("tags", {})
            name = t.get("name") or t.get("brand") or ""
            if not name:
                continue
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            addr = " ".join(x for x in [t.get("addr:housenumber", ""), t.get("addr:street", ""),
                                        t.get("addr:city", ""), t.get("addr:state", ""),
                                        t.get("addr:postcode", "")] if x).strip()
            socials = [t[k] for k in ("contact:facebook", "contact:instagram", "contact:twitter") if t.get(k)]
            out.append(RawBiz(
                name=name, provider=self.name, lat=lat, lon=lon,
                phone=t.get("phone") or t.get("contact:phone", ""),
                website=t.get("website") or t.get("contact:website", ""),
                email=t.get("email") or t.get("contact:email", ""),
                address=addr, socials=socials,
                category=spec.category, last_seen=el.get("timestamp", ""),
                url=f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
            ))
        return out


class OvertureProvider:
    name = "overture"
    needs_key = False
    key_env = ""
    update_frequency = "monthly release (Linux Foundation; ~25 data partners)"
    reliability = "confidence-scored + source lineage; broadest coverage; phone/website richer than OSM"
    license = "CDLA-Permissive 2.0 (commercial-clean, no share-alike)"
    weight = 0.85

    def available(self, config) -> bool:
        try:
            import overturemaps  # noqa: F401
            return True
        except ImportError:
            return False

    def search(self, spec: SearchSpec) -> list[RawBiz]:
        # overturemaps CLI resolves the current release + streams geojsonseq for a bbox.
        import subprocess
        s, w, n, e = spec.bbox
        cmd = ["overturemaps", "download", f"--bbox={w},{s},{e},{n}", "-f", "geojsonseq", "--type=place"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=spec.config.get("overture_timeout", 240))
        if proc.returncode != 0:
            raise RuntimeError(f"overturemaps failed: {proc.stderr[:200]}")
        cats = {c.lower() for c in spec.taxon.overture}
        out = []
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            try:
                g = json.loads(line)
            except json.JSONDecodeError:
                continue
            p = g.get("properties", {})
            cat = ((p.get("categories") or {}).get("primary") or "").lower()
            alt = {a.lower() for a in ((p.get("categories") or {}).get("alternate") or [])}
            if cats and cat not in cats and not (cats & alt):
                continue
            name = (p.get("names") or {}).get("primary") or ""
            if not name:
                continue
            coords = (g.get("geometry") or {}).get("coordinates") or [None, None]
            phones = p.get("phones") or []
            sites = p.get("websites") or []
            emails = p.get("emails") or []
            socials = p.get("socials") or []
            addrs = p.get("addresses") or []
            addr = ""
            if addrs:
                a = addrs[0]
                addr = " ".join(x for x in [a.get("freeform", ""), a.get("locality", ""),
                                            a.get("region", ""), a.get("postcode", "")] if x).strip()
            out.append(RawBiz(
                name=name, provider=self.name, lat=coords[1], lon=coords[0],
                phone=phones[0] if phones else "", website=sites[0] if sites else "",
                email=emails[0] if emails else "", address=addr,
                socials=list(socials), category=cat or spec.category,
                confidence=p.get("confidence"), url=f"overture:{p.get('id', '')}",
            ))
            if len(out) >= spec.limit * 3:
                break
        return out


class FsqOpenProvider:
    name = "fsq_open"
    needs_key = False
    key_env = ""
    update_frequency = "monthly release (Foundry/Foursquare open data on Hugging Face)"
    reliability = "~100M global POIs; strong urban coverage; category-rich"
    license = "Apache-2.0 (commercial-clean)"
    weight = 0.8

    def available(self, config) -> bool:
        # Bulk dataset: fast only against a LOCAL parquet dir (100 remote HF shards per query has
        # no spatial index -> too slow to scan live). Point PITH_FSQ_PARQUET / config['fsq_dir']
        # at a downloaded release dir (…/places/parquet). Absent -> provider cleanly skipped.
        path = config.get("fsq_dir") or os.environ.get("PITH_FSQ_PARQUET", "")
        if not path or not os.path.isdir(path):
            return False
        try:
            import duckdb  # noqa: F401
            return True
        except ImportError:
            return False

    def search(self, spec: SearchSpec) -> list[RawBiz]:
        import duckdb
        path = spec.config.get("fsq_dir") or os.environ["PITH_FSQ_PARQUET"]
        s, w, n, e = spec.bbox
        terms = spec.taxon.fsq or (spec.taxon.term,)
        like = " OR ".join(f"lower(fsq_category_labels::VARCHAR) LIKE '%{t.lower()}%'" for t in terms)
        con = duckdb.connect()
        q = f"""SELECT name, tel, website, email, latitude, longitude, fsq_place_id,
                       address, locality, region, postcode
                FROM read_parquet('{os.path.join(path, '*.parquet')}')
                WHERE latitude BETWEEN {s} AND {n} AND longitude BETWEEN {w} AND {e}
                  AND ({like}) LIMIT {spec.limit * 3}"""
        rows = con.execute(q).fetchall()
        out = []
        for name, tel, site, email, lat, lon, fid, addr, loc, reg, pc in rows:
            if not name:
                continue
            full = " ".join(x for x in [addr or "", loc or "", reg or "", pc or ""] if x).strip()
            out.append(RawBiz(name=name, provider=self.name, lat=lat, lon=lon, phone=tel or "",
                              website=site or "", email=email or "", address=full,
                              category=spec.category, url=f"https://foursquare.com/v/{fid}"))
        return out


class _KeyedProvider:
    """Base for API providers that need a (free) key. `search` = fetch + parse; `_parse` is split
    out so it's unit-testable offline. Available only when the key is configured."""
    needs_key = True

    def available(self, config) -> bool:
        return bool(_key_for(self, config))

    def _fetch(self, spec: SearchSpec) -> dict:
        raise NotImplementedError

    def _parse(self, payload: dict, spec: SearchSpec) -> list[RawBiz]:
        raise NotImplementedError

    def search(self, spec: SearchSpec) -> list[RawBiz]:
        return self._parse(self._fetch(spec), spec)


class YelpProvider(_KeyedProvider):
    name = "yelp"
    key_env = "PITH_YELP_KEY"
    update_frequency = "live API (Yelp-maintained; near real-time)"
    reliability = "strong US SMB coverage, phone + address + ratings; no website/email in payload"
    license = "Yelp Fusion ToS — display use; storing/reselling restricted"
    weight = 0.8

    def _fetch(self, spec):
        q = urllib.parse.urlencode({"term": spec.taxon.term or spec.category,
                                    "latitude": spec.geo["lat"], "longitude": spec.geo["lon"],
                                    "limit": min(50, spec.limit)})
        raw = _get(f"https://api.yelp.com/v3/businesses/search?{q}",
                   headers={"Authorization": f"Bearer {_key_for(self, spec.config)}"}, timeout=30)
        return json.loads(raw)

    def _parse(self, payload, spec):
        out = []
        for b in payload.get("businesses", []):
            coord = b.get("coordinates") or {}
            out.append(RawBiz(name=b.get("name", ""), provider=self.name,
                              lat=coord.get("latitude"), lon=coord.get("longitude"),
                              phone=b.get("phone") or b.get("display_phone", ""),
                              address=", ".join((b.get("location") or {}).get("display_address", [])),
                              category=spec.category, url=b.get("url", "")))
        return [r for r in out if r.name]


class GoogleProvider(_KeyedProvider):
    name = "google"
    key_env = "PITH_GOOGLE_KEY"
    update_frequency = "live API (Google Places, New; best freshness)"
    reliability = "highest completeness + freshness; phone + website + address"
    license = "Google Places ToS — caching limited, storing/reselling restricted"
    weight = 0.9

    def _fetch(self, spec):
        body = json.dumps({"textQuery": f"{spec.taxon.term or spec.category} in {spec.location}",
                           "maxResultCount": min(20, spec.limit)}).encode()
        raw = _get("https://places.googleapis.com/v1/places:searchText", data=body,
                   headers={"Content-Type": "application/json",
                            "X-Goog-Api-Key": _key_for(self, spec.config),
                            "X-Goog-FieldMask": "places.displayName,places.nationalPhoneNumber,"
                                                "places.websiteUri,places.formattedAddress,places.location"},
                   timeout=30)
        return json.loads(raw)

    def _parse(self, payload, spec):
        out = []
        for p in payload.get("places", []):
            loc = p.get("location") or {}
            out.append(RawBiz(name=(p.get("displayName") or {}).get("text", ""), provider=self.name,
                              lat=loc.get("latitude"), lon=loc.get("longitude"),
                              phone=p.get("nationalPhoneNumber", ""), website=p.get("websiteUri", ""),
                              address=p.get("formattedAddress", ""), category=spec.category))
        return [r for r in out if r.name]


class FsqApiProvider(_KeyedProvider):
    name = "fsq_api"
    key_env = "PITH_FSQ_KEY"
    update_frequency = "live API (Foursquare Places; near real-time)"
    reliability = "global POIs, category-rich; phone + website + address"
    license = "Foursquare Places API ToS — attribution; storage limited"
    weight = 0.8

    def _fetch(self, spec):
        q = urllib.parse.urlencode({"query": spec.taxon.term or spec.category,
                                    "ll": f"{spec.geo['lat']},{spec.geo['lon']}",
                                    "limit": min(50, spec.limit),
                                    "fields": "name,tel,website,email,location,latitude,longitude,fsq_place_id"})
        raw = _get(f"https://places-api.foursquare.com/places/search?{q}",
                   headers={"Authorization": f"Bearer {_key_for(self, spec.config)}",
                            "X-Places-Api-Version": "2025-06-17"}, timeout=30)
        return json.loads(raw)

    def _parse(self, payload, spec):
        out = []
        for p in payload.get("results", []):
            loc = p.get("location") or {}
            out.append(RawBiz(name=p.get("name", ""), provider=self.name,
                              lat=p.get("latitude"), lon=p.get("longitude"),
                              phone=p.get("tel", ""), website=p.get("website", ""),
                              email=p.get("email", ""), address=loc.get("formatted_address", ""),
                              category=spec.category, url=f"https://foursquare.com/v/{p.get('fsq_place_id','')}"))
        return [r for r in out if r.name]


# All providers on one contract. Keyless (overpass/overture/fsq_open) + keyed (yelp/google/fsq_api).
# Keyed providers read their key from config[key_env] or os.environ[key_env]; without it they
# report available()->False and find_businesses records them in coverage.skipped — never an error.
PROVIDERS: dict[str, object] = {p.name: p for p in (
    OverpassProvider(), OvertureProvider(), FsqOpenProvider(),
    YelpProvider(), GoogleProvider(), FsqApiProvider(),
)}

_WEIGHTS = {name: getattr(p, "weight", 0.5) for name, p in PROVIDERS.items()}


def register(provider) -> None:
    """Add a provider to the registry (used by the keyed-provider module + tests)."""
    PROVIDERS[provider.name] = provider
    _WEIGHTS[provider.name] = getattr(provider, "weight", 0.5)


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

def _key_for(p, config: dict) -> str:
    return (config.get(p.key_env) or os.environ.get(p.key_env, "")) if getattr(p, "key_env", "") else ""


def find_businesses(category: str, location: str, sources="auto", limit: int = 100,
                    radius_km: Optional[float] = None, config: Optional[dict] = None,
                    has_website: bool = False, has_phone: bool = False,
                    min_confidence: float = 0.0) -> dict:
    """Discover local businesses across every enabled+available provider, then waterfall-merge
    into confidence-scored records. Returns {businesses, coverage, geo}. Evidence, not answers:
    each business keeps which providers attest each field.

    sources: "auto" (all available) | list of provider names.
    Filters are opt-in and applied AFTER merge so you see what was dropped in coverage.
    """
    config = config or {}
    geo = geocode(location)
    if radius_km:
        bbox = _bbox_from_radius(geo["lat"], geo["lon"], radius_km)
    else:
        bbox = geo["bbox"]
    taxon = _taxon(category)
    spec = SearchSpec(category=category, taxon=taxon, location=location, geo=geo,
                      bbox=bbox, limit=limit, config=config)

    names = list(PROVIDERS) if sources == "auto" else list(sources)
    coverage = {"requested": names, "ran": [], "skipped": {}, "counts": {}, "errors": {}}
    chosen = []
    for nm in names:
        p = PROVIDERS.get(nm)
        if p is None:
            coverage["skipped"][nm] = "unknown provider"
        elif not p.available(config):
            coverage["skipped"][nm] = ("needs key: " + p.key_env) if getattr(p, "needs_key", False) \
                else "provider unavailable (pip install 'pith[places]')"
        else:
            chosen.append(p)

    raws: list[RawBiz] = []

    def run(p):
        return p.name, p.search(spec)

    if chosen:
        with ThreadPoolExecutor(max_workers=min(6, len(chosen))) as pool:
            for nm, res in _as_completed(pool, chosen, run, coverage):
                coverage["ran"].append(nm)
                coverage["counts"][nm] = len(res)
                raws.extend(res)

    merged = [_merge_cluster(c, _WEIGHTS) for c in _cluster(raws)]

    filtered = []
    for b in merged:
        if has_website and not b._best("website"):
            continue
        if has_phone and not b._best("phone"):
            continue
        if b.confidence < min_confidence:
            continue
        filtered.append(b)
    filtered.sort(key=lambda b: (-b.confidence, -len(b.providers), b.name.lower()))
    filtered = filtered[:limit]

    coverage["merged_total"] = len(merged)
    coverage["after_filters"] = len(filtered)
    coverage["source_meta"] = {p.name: {"update_frequency": p.update_frequency,
                                         "reliability": p.reliability, "license": p.license,
                                         "needs_key": getattr(p, "needs_key", False)}
                               for p in PROVIDERS.values()}
    return {"businesses": [b.as_dict() for b in filtered], "coverage": coverage,
            "geo": {"display": geo["display"], "lat": geo["lat"], "lon": geo["lon"], "bbox": bbox}}


def _as_completed(pool, providers, run, coverage):
    """Run providers concurrently; a failing provider is recorded in coverage, never sinks the run."""
    futs = {pool.submit(run, p): p for p in providers}
    from concurrent.futures import as_completed
    for fut in as_completed(futs):
        p = futs[fut]
        try:
            yield fut.result()
        except Exception as e:                       # one bad source shouldn't kill discovery
            coverage["errors"][p.name] = str(e)[:200]


if __name__ == "__main__":
    import sys
    # self-check: waterfall clustering + field aggregation are deterministic (offline, no network)
    a = RawBiz(name="Joe's Plumbing LLC", provider="overpass", lat=33.45, lon=-112.07,
               phone="(602) 555-1212", website="http://joesplumbing.com")
    b = RawBiz(name="Joe's Plumbing", provider="overture", lat=33.4501, lon=-112.0701,
               website="https://www.joesplumbing.com/", email="joe@joesplumbing.com", confidence=0.9)
    c = RawBiz(name="Unrelated Cafe", provider="overpass", lat=33.9, lon=-112.9)
    clusters = _cluster([a, b, c])
    assert len(clusters) == 2, clusters
    biz = _merge_cluster(next(cl for cl in clusters if len(cl) == 2), _WEIGHTS)
    assert biz.fields["website"].corroboration == 2, "both sources attest the site"
    assert set(biz.providers) == {"overpass", "overture"}
    assert biz.confidence > 0.6, biz.confidence           # two independent sources -> confident
    assert biz._best("email") == "joe@joesplumbing.com"   # single-source field still surfaced
    print("leads.py self-check OK:", biz.name, "conf", round(biz.confidence, 2),
          "site corrob", biz.fields["website"].corroboration)
    if len(sys.argv) > 2:      # live: python -m pith.leads "dentists" "Phoenix, AZ"
        import pprint
        r = find_businesses(sys.argv[1], sys.argv[2], limit=int(sys.argv[3]) if len(sys.argv) > 3 else 20)
        pprint.pp(r["coverage"])
        for x in r["businesses"][:8]:
            print(f"  {x['confidence']:.2f} [{'+'.join(x['providers'])}] {x['name']} | {x['phone']} | {x['website']}")
