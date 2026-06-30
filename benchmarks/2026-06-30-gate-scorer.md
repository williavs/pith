# Fetch-budget gate: which scorer? — measured, the fancy one lost (2026-06-30)

The gate ranks candidate URLs by buyer-signal relevance to a target, BEFORE spending the
~4-5s walled fetch. Question: LLM-per-URL (jim's pick), a tiny weighted embedder
(model2vec/potion-retrieval-32M, the "2026 with-weights" pick), or something tinier?

Tested on a labeled set: 12 real dossier signals for "Matt MacInnis @ Rippling" + 20
plausible-junk URLs (competitors, wrong people, boilerplate, noise). `benchmarks/gate_eval.py`.

## Result — token-overlap beats the weighted embedder

| input available | scorer | precision@12 | wasted-fetch cut |
|---|---|---|---|
| URL only | keyword (token overlap) | 0.83 | +44% |
| URL only | potion-retrieval-32M (semantic) | 0.75 | +0% |
| **+ search snippet** | **keyword (token overlap)** | **1.00** | **+59%** |
| + search snippet | potion-retrieval-32M (semantic) | 0.83 | +52% |

The 270MB+numpy weighted model **lost to ~4 lines of stdlib token-matching in both
conditions.** Keyword-over-snippet is perfect (1.00 precision@12).

## Why semantic embedding is the wrong tool here

The gate's job is **identity matching** — "is this page about *this* person at *this*
company" — which is lexical: the entity name either appears or it doesn't. potion does
**semantic similarity**, so it ranks topical neighbors up: "Deel — global payroll" scores
close to "Rippling — HR platform" because they're the same *topic*, and the gate fetches the
competitor. Semantic generalization is a **liability** when you need entity precision.

Token-overlap naturally ranks signal above boilerplate too: a signal snippet mentions
person + role + company (3-4 query tokens hit), while "Privacy Policy | Rippling" hits only
one — so the rich-match pages float to the top without any model.

## The real lever is the snippet, not the scorer

The jump that mattered was **URL-only → +snippet** (0.83 → 1.00), not keyword → embedder.
The gate just needs each candidate's title/snippet, which is **free**: search results carry
it, and a crawl has the anchor text. No model, no LLM, no API, no 270MB dependency.

## Decisions

- **Gate scorer = token overlap of the target query against `url + snippet`.** Stdlib,
  deterministic, sub-µs, zero new dep. Shipped as `score`/`gate` in cli.py.
- **Rejected model2vec** for the gate: measured worse, and adds numpy + ~130MB weights for a
  net loss. (Kept installed in the dev venv only so this benchmark reproduces; NOT a project
  dep.) A weighted embedder may still earn its place at the *downstream* step — semantic
  dedup/clustering of extracted signals — where the task is genuinely semantic. Re-measure
  there before adding it.
- **Rejected LLM-per-URL** (jim's pick): the gate's input is short identity strings; an LLM
  is overkill and prone to the same topic-vs-entity confusion. Spend the LLM budget on the
  one place it's irreplaceable — turning fetched content into typed `{entity, signal,
  evidence}` objects.
