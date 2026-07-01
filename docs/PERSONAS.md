# pith — who it's for (north star)

**Decision (2026-07-01, Willy): all four personas, businesses AND people equally.**

pith is a **neutral, shared extraction + enrichment SDK** for public data. It is excellent at
one primitive — *turn a public URL or a thin fact into clean, deterministic, structured data*
— and every persona is served by **composition on top of that core**, not by forking it. The
core stays neutral; differentiation lives in the apps/examples.

No LLM inside. Deterministic. Public-only. Browser/tier complexity hidden.

## The four personas

| # | Persona | Starts with | Wants | Optimizes for | Entry point |
|---|---|---|---|---|---|
| 1 | **SDR / Sales rep** (GTM) | a market (category+geo) or company list | enriched company lead lists | volume + firmographic accuracy | `directory_search` → `website_intel` → `find_contact` · `examples/build_sales_list.py` |
| 2 | **Solo agency founder** (Scout) | a cold-call-friendly geo | dated-site businesses + owner contact + pitch hooks | depth per lead | `examples/scout/` |
| 3 | **Investigator** (OSINT / Corn) | a thin fact (email/handle/name) | a person's accounts, corroborated identity, provenance | **precision** — a false positive is a real cost | `verify_email` · `gravatar_profile` · `enumerate_profiles` · `resolve_person` · `examples/investigate.py` |
| 4 | **Developer / integrator** | pith itself | clean SDK/API, deterministic JSON, no LLM baggage | DX, language-agnostic access | `from pith import Extractor` · `python -m pith.serve` |

Persona 4 is the **delivery layer** for 1–3. Personas 1–2 are *business*-centric; persona 3
is *people*-centric; the shared primitive (extract contact/identity from a public page) is why
one core serves both.

## The tension, and how it's resolved

GTM wants **volume + businesses**; OSINT wants **precision + people**. They tune oppositely.
Resolution: the **core is neutral and honest** (deterministic output, corroboration surfaced,
coverage gaps reported, no silent false positives), and each persona composes it differently.
We do NOT bias the core toward one — we make the primitives trustworthy for both and let the
examples/apps express the persona.

## What this means for building

- A change to the **core** (extract/fetch/serve) must serve the shared primitive and stay
  persona-neutral. If a change only helps one persona, it belongs in an **example/app**, not
  the core.
- Precision is non-negotiable for persona 3: no fabricated accounts, corroboration + coverage
  always surfaced. (Already enforced — see the adversarial fault-hunt fixes.)
- Every capability ships with a **real-data example** that teaches its best use.

## Open questions for Willy

- Is there a 5th persona (e.g. journalist, recruiter, security researcher) worth a first-class
  example, or are these four the set?
- For persona 1 (SDR): is the target input usually a **category+geo** (directory) or a
  **given company list to enrich**? That changes which path we harden next.
