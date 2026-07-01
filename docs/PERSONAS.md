# pith — who it's for (north star)

**Decision (2026-07-01, Willy): all four personas, businesses AND people equally.**

pith is a **neutral, shared extraction + enrichment SDK** for public data. It is excellent at
one primitive — *turn a public URL or a thin fact into clean, deterministic, structured data*
— and every persona is served by **composition on top of that core**, not by forking it. The
core stays neutral; differentiation lives in the apps/examples.

No LLM inside. Deterministic. Public-only. Browser/tier complexity hidden.

## The personas

**Core set** (each has a dedicated real-data example):

| # | Persona | Starts with | Wants | Optimizes for | Entry point |
|---|---|---|---|---|---|
| 1 | **SDR / Sales rep** (GTM) | a market **or** a list you hold | enriched company lead lists | volume + firmographic accuracy | build: `examples/build_sales_list.py` · enrich: `examples/enrich_list.py` |
| 2 | **Solo agency founder** (Scout) | a cold-call-friendly geo | dated-site businesses + owner contact + pitch hooks | depth per lead | `examples/scout/` |
| 3 | **Investigator** (OSINT / Corn) | a thin fact (email/handle/name) | a person's accounts, corroborated identity, provenance | **precision** — a false positive is a real cost | `examples/investigate.py` |
| 4 | **Developer / integrator** | pith itself | clean SDK/API, deterministic JSON, no LLM baggage | DX, language-agnostic access | `from pith import Extractor` · `python -m pith.serve` |

Persona 4 is the **delivery layer** for the rest. 1–2 are *business*-centric; 3 is
*people*-centric. The shared primitive (extract contact/identity from a public page) is why
one core serves both.

**Both SDR input shapes are first-class** (Willy: "all kinds of models and situations happen
in the wild"): `build_sales_list.py` builds from a category+geo; `enrich_list.py` enriches a
company list you already have. Same `enrich_company` / `find_contact` primitives underneath.

**Adjacent personas** (real, served by *composing existing primitives* — promote to a dedicated
example on demand):

| Persona | Composes | Missing primitive (if any) |
|---|---|---|
| **Journalist / researcher** | `investigate.py` flow + provenance | per-datum source+timestamp export (case-file) |
| **Recruiter / talent sourcer** | `gravatar_profile` + `enumerate_profiles` + GitHub/portfolio extract | reverse-source from a repo/portfolio |
| **Security researcher** (defensive) | `Extractor` + `website_intel` + `enumerate_profiles` | crt.sh subdomain enum; the SSRF guard already matters here |

These need **no core changes** — they're example compositions, which is the whole point of the
neutral-SDK model.

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

## Resolved (2026-07-01)

- **More personas: yes.** Journalist / recruiter / security-researcher are real and adjacent;
  they compose existing primitives. Promote to dedicated examples on demand.
- **SDR input: both.** Build-from-market and enrich-a-held-list are both first-class.
