"""The evidence model — pith's core stance: return EVIDENCE, never answers.

Every fact pith surfaces carries where it came from. Aggregation UNIONS evidence and COUNTS
corroboration; it never collapses to a single "primary" pick or a hidden confidence scalar.
The caller (an LLM or a person) applies judgment over the evidence — pith's job is to make
that evidence clean, typed, sourced, and honest about what it could not determine.

Why: six personas using the old convenience wrappers all hit the same failure — the wrapper
made a call (picked a primary email, scored an identity) and threw away the evidence beneath,
producing a confident answer that was worse than the raw data. Evidence-not-answers removes
that entire failure class.

    Fact      — one value (an email/phone/social/name) + every Source that attests it.
    Source    — where a value was observed (url + method + when).
    Coverage  — what was checked, what succeeded, what was inconclusive (never a silent gap).
    aggregate — union many observations into deduped Facts, corroboration = distinct sources.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Source:
    """Where a datum was observed. `method` is HOW it was found — the extraction path — which
    is itself signal (schema.org/whois are authoritative; scraped href/text are weaker)."""
    url: str
    method: str                     # text | mailto | tel | schema.org | cfemail | atdot | og | whois | gravatar
    fetched_at: str = ""            # ISO8601 at fetch; "" for pure-string extraction (keeps offline tests deterministic)


@dataclass
class Fact:
    """One value with its provenance. `corroboration` = how many DISTINCT source URLs attest
    it — the same waterfall idea, now first-class. `labels` are transparent classifications
    (email_type, line_type, region...) the caller can see and override — never a hidden pick."""
    value: str
    kind: str                       # email | phone | social | name | account | address
    sources: list[Source] = field(default_factory=list)
    labels: dict = field(default_factory=dict)

    @property
    def corroboration(self) -> int:
        return len({s.url for s in self.sources})

    @property
    def methods(self) -> list[str]:
        return sorted({s.method for s in self.sources})

    def as_dict(self) -> dict:
        return {"value": self.value, "kind": self.kind, "corroboration": self.corroboration,
                "labels": self.labels,
                "sources": [{"url": s.url, "method": s.method, **({"fetched_at": s.fetched_at} if s.fetched_at else {})}
                            for s in self.sources]}


@dataclass
class Coverage:
    """What pith actually looked at — so a gap is never read as an absence. `inconclusive` is
    the honest middle (bot-walled / unreachable): NOT 'nothing there', just 'couldn't tell'."""
    checked: list[str] = field(default_factory=list)
    ok: list[str] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)          # [{url, error}]
    inconclusive: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"checked": len(self.checked), "ok": len(self.ok), "failed": self.failed,
                "inconclusive": self.inconclusive}


def aggregate(observations) -> list[Fact]:
    """Union observations into deduped Facts. An observation is (value, kind, Source, labels?).
    Same (kind, normalized-value) merges: sources unioned, labels merged (first-writer wins per
    key). Returns Facts sorted by corroboration desc — ranked, never PICKED. Nothing dropped."""
    by_key: dict[tuple, Fact] = {}
    for obs in observations:
        value, kind, source = obs[0], obs[1], obs[2]
        labels = obs[3] if len(obs) > 3 else {}
        if not value:
            continue
        key = (kind, value.strip().lower())
        f = by_key.get(key)
        if f is None:
            by_key[key] = Fact(value=value, kind=kind, sources=[source], labels=dict(labels))
        else:
            f.sources.append(source)
            for k, v in labels.items():
                f.labels.setdefault(k, v)
    return sorted(by_key.values(), key=lambda f: (-f.corroboration, f.kind, f.value.lower()))
