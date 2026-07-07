# pith recipes — runnable scripts

Each is a real, copy-paste script. Run with:
`uv run --with "pith[osint,email] @ git+https://github.com/williavs/pith.git@master" --with pandas --with openpyxl python script.py`

## 1 · Clean + validate a contact list (offline + deliverability, deduped)

The high-volume job. Offline checks scale to 100k+ in seconds; deliverability dedupes by domain.

```python
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
from pith import verify_email
from pith.phoneintel import phone_intel
from pith.extract import _domain_has_mx, _domain_resolves   # cached, bounded DNS helpers

df = pd.read_excel("contacts.xlsx", dtype={"email": str, "phone": str})  # str! else '+1..' -> int, '+' lost

# offline, every row
ev = [verify_email(str(e)) if pd.notna(e) else {"valid_syntax": False} for e in df["email"]]
df["email_ok"]   = [x.get("valid_syntax") for x in ev]
df["is_role"]    = [x.get("is_role") for x in ev]
df["is_free"]    = [x.get("is_freemail") for x in ev]
df["email_dom"]  = [x.get("domain", "") for x in ev]
pi = [phone_intel(str(p)) if pd.notna(p) else {} for p in df["phone"]]
df["phone_ok"]   = [x.get("valid", False) for x in pi]
df["phone_e164"] = [x.get("e164", "") for x in pi]

# deliverability, deduped by domain (24k domains for a 73k list — the whole speedup) + bounded/parallel
domains = sorted({d for d in df["email_dom"] if d})
def check(d): return d, (_domain_resolves(d), _domain_has_mx(d))   # has_mx=None if dnspython missing
with ThreadPoolExecutor(max_workers=100) as pool:
    dmap = dict(pool.map(check, domains))
df["has_mx"] = [dmap.get(d, (0, None))[1] for d in df["email_dom"]]

# trim: keep deliverable, deduped
df["dup"] = df["email"].str.lower().duplicated()
keep = df[(df["email_ok"]) & (~df["is_role"]) & (df["has_mx"] != False) & (~df["dup"])]  # noqa: E712
keep.to_csv("cleaned.csv", index=False)
print(f"{len(df):,} -> {len(keep):,} contactable")
```

## 2 · Company dossier (sell-into signals for one account)

```python
from pith.cli import contact_evidence, website_intel
from pith.recipes import owner_email, people
from pith.jobs import jobs_search
from pith.news import news_search
from pith.financials import company_intel

name, domain = "Ramp", "ramp.com"
ev = contact_evidence("https://" + domain)          # contacts + people + firmographics, one crawl
wi = website_intel("https://" + domain)             # tech stack + modernness
jb = jobs_search(name, domain)                      # hiring (growth signal)
nw = news_search(name, domain=domain, window_days=120)
ci = company_intel(name)                             # SEC/funding (public+funded co's)

print("email:", (owner_email(ev["facts"]) or "—"))
print("firmographics:", ev["firmographics"])         # rating/hours/employees/founded when published
print("tech:", wi.get("framework"), wi.get("modernness_grade"))
print("hiring:", jb["count"], "open,", jb["ats"])
sig = {}
for it in nw:
    if it["signal"] and it["signal"] != "news": sig[it["signal"]] = sig.get(it["signal"], 0) + 1
print("news signals:", sig)                          # {'funding':28,'ai':35,...} -> why reach out now
print("funding:", (ci.get("funding") or {}).get("raises", [])[:1])
```

To rank a shortlist, run this per company (dedupe your list to unique domains first, `ThreadPoolExecutor(max_workers=6)`), and score transparently, e.g.:
`score = 2*min(open_roles,20) + 15*bool(funding_or_funding_news) + 5*has_ai_or_product_news + 5*(modernness in "AB")`.

## 3 · Person → multi-channel reach (OSINT)

```python
from pith.profiles import enumerate_profiles
from pith.gravatar import gravatar_profile
from pith.phoneintel import phone_intel

# from an email you already have
g = gravatar_profile("someone@company.com")          # -> linked GitHub/socials if they use gravatar
if g.get("exists"): print(g.get("display_name"), g.get("accounts"))

# from a handle (e.g. derived from their name or an existing profile url)
r = enumerate_profiles("janesmith", report=True)      # ~480 sites, existence only
for p in r["profiles"][:10]:
    print(p["site"], p["url"])                         # X, GitHub, Medium... = channels to reach them
# coverage tells you what could NOT be checked — an empty roster is honest, not a failure
```

**Verify before you trust a match** (name collisions are real):

```python
from pith.recipes import accept_identity
# corroborations: [{candidate_url, signals:[{name, source_url}]}] gathered from the profiles above
accept = accept_identity(corroborations, min_signals=2, exclude_self=True)   # your rules, not a hidden score
```

## 4 · Discover a prospect list from a market

```python
from pith.leads import find_businesses
res = find_businesses("med spas", "Scottsdale, AZ", limit=100, has_website=True)   # keyless (OSM/Overpass)
for b in res["businesses"]:
    print(b["confidence"], b["name"], b["website"], b["phone"])
# then enrich the ones with sites via workflow 2. Storefront categories work best.
```
