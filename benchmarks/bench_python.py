"""Python (pith core) extraction benchmark.

Reads each local HTML fixture and runs the exact pith extraction step
(trafilatura -> markdown). Fetch and the stealth browser are excluded: they're
language-agnostic / pith-unique, so the fair cross-language comparison is the
boilerplate-strip + markdownify core, given identical HTML.

Output: CSV rows `lang,fixture,ms_median,out_bytes` to stdout — same protocol as
the Go and Rust harnesses, so combine.py can table them side by side.
"""
import glob
import os
import statistics
import time

import trafilatura

REPS = 7
FIXTURES = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "fixtures", "*.html")))


def extract(html: str):
    return trafilatura.extract(html, output_format="markdown", include_links=True, with_metadata=True)


def main():
    for path in FIXTURES:
        html = open(path, encoding="utf-8", errors="ignore").read()
        out = extract(html) or ""
        times = []
        for _ in range(REPS):
            t = time.perf_counter()
            extract(html)
            times.append((time.perf_counter() - t) * 1000)
        name = os.path.basename(path)
        print(f"python:trafilatura,{name},{statistics.median(times):.1f},{len(out.encode())}")


if __name__ == "__main__":
    main()
