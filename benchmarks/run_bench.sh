#!/usr/bin/env bash
# Run all three extraction harnesses on the shared fixtures and print a unified
# table. Each harness emits `lang,fixture,ms_median,out_bytes`; combine.py joins them.
#
# Prereqs: ../.venv (pith installed), go, cargo. Fixtures in ./fixtures.
set -euo pipefail
cd "$(dirname "$0")"

PY=../.venv/bin/python

{
  $PY bench_python.py
  ( cd go && go run . )
  ( cd rust && cargo build --release -q && ./target/release/pithbench )
} | $PY combine.py
