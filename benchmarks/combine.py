"""Read `lib,fixture,ms_median,out_bytes` CSV rows from stdin, print two markdown
tables (speed, output size) with libraries as rows and fixtures as columns, plus a
summary ranking by total time. Used by run_bench.sh."""
import sys
from collections import defaultdict

ms = defaultdict(dict)     # lib -> fixture -> ms
by = defaultdict(dict)     # lib -> fixture -> bytes
libs, fixtures = [], []
for line in sys.stdin:
    line = line.strip()
    if not line or line.startswith("lang,") or line.startswith("lib,"):
        continue
    lib, fx, t, n = line.split(",")
    fx = fx.replace(".html", "")
    ms[lib][fx] = float(t)
    by[lib][fx] = int(n)
    if lib not in libs:
        libs.append(lib)
    if fx not in fixtures:
        fixtures.append(fx)


def table(title, data, fmt):
    print(f"\n### {title}\n")
    print("| library | " + " | ".join(fixtures) + " |")
    print("|" + "---|" * (1 + len(fixtures)))
    for lib in libs:
        cells = " | ".join(fmt(data[lib].get(fx)) for fx in fixtures)
        print(f"| {lib} | {cells} |")


table("Extraction time (ms, median of 7, lower=faster)", ms, lambda v: f"{v:.1f}" if v is not None else "-")
table("Output size (bytes, higher usually=more content captured)", by, lambda v: f"{v}" if v is not None else "-")

# ranking by total ms across fixtures
print("\n### Total time across all fixtures (ms)\n")
print("| library | total ms | vs python |")
print("|---|---|---|")
totals = {lib: sum(ms[lib].values()) for lib in libs}
base = next((totals[l] for l in libs if l.startswith("python")), None)
for lib, tot in sorted(totals.items(), key=lambda x: x[1]):
    rel = f"{base / tot:.1f}x faster" if base and tot else "-"
    print(f"| {lib} | {tot:.1f} | {rel} |")
