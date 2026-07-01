"""Enrich a company list you ALREADY have — the other half of the SDR pipeline.

build_sales_list.py BUILDS a list from a market (category+geo). This one takes a list you
already hold (a CRM export, a conference attendee list, a scraped set of domains) and fills in
the firmographic + contact columns pith can derive from each company's own site:

    name, website ──► enrich_company ──► linkedin/github/twitter, company emails,
                                          careers-page?, tech stack + modernness grade

Concurrent, deterministic, public-only. Output is CSV (default) or JSON — drop it back into
the CRM.

Input: a file with one company per line, `Name,https://website` (name optional — bare
domains work too), or pass companies as args.

Run:  python examples/enrich_list.py companies.txt
      python examples/enrich_list.py stripe.com https://linear.app "Acme, acme.com"
"""
import csv
import io
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pith.cli import enrich_company


def _parse(line: str):
    """'Name,website' | 'website' -> (name, normalized_url)."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    name, _, rest = line.partition(",")
    if rest.strip():                       # "Name, url"
        website = rest.strip()
    else:                                  # bare domain/url -> derive a name from the domain
        website = name.strip()
        name = website.split("//")[-1].split("/")[0].replace("www.", "").split(".")[0].title()
    if not website.startswith(("http://", "https://")):
        website = "https://" + website.lstrip("/")
    return name, website


def enrich_list(companies: list[tuple[str, str]], workers: int = 6) -> list[dict]:
    def one(nc):
        name, website = nc
        try:
            return enrich_company(name, website)
        except Exception as e:
            print(f"  skip {website}: {str(e)[:50]}", file=sys.stderr)
            return {"company": name, "website": website, "error": str(e)[:60]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, companies))
    for r in rows:
        print(f"  {r['company'][:24]:24} grade {r.get('grade','?')} · "
              f"{len(r.get('emails') or [])}✉ · linkedin={'y' if r.get('linkedin') else '-'}", file=sys.stderr)
    return rows


def _to_csv(rows):
    cols = ["company", "website", "grade", "builder", "hosted", "linkedin", "github", "twitter", "careers", "emails"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({**r, "emails": "; ".join(r.get("emails") or [])})
    return buf.getvalue().rstrip()


if __name__ == "__main__":
    args = sys.argv[1:]
    lines = []
    if len(args) == 1 and Path(args[0]).is_file():
        lines = Path(args[0]).read_text().splitlines()
    else:
        lines = args or ["stripe.com", "https://linear.app"]
    companies = [c for c in (_parse(x) for x in lines) if c]
    print(f"┌─ enriching {len(companies)} companies", file=sys.stderr)
    rows = enrich_list(companies)
    print("└─ done\n", file=sys.stderr)
    fmt = "json" if "--json" in args else "csv"
    print(json.dumps(rows, indent=2) if fmt == "json" else _to_csv(rows))
