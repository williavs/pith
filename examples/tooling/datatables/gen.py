"""Run pith across a curated input matrix (normal + edge cases) and emit a self-contained
HTML of sortable datatables — so you can SEE the actual data pith returns, including the
ugly cases (false positives, IDN/unicode, malformed input, empty results).

    python examples/datatables/gen.py     # writes examples/datatables/index.html
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pith import Extractor, verify_email
from pith.extract import emails, phones, socials, structured
from pith.cli import website_intel, directory_search
from pith.profiles import enumerate_profiles
from pith.gravatar import gravatar_profile
from pith.phoneintel import phone_intel

HERE = Path(__file__).resolve().parent
tables = []


def add(title, note, columns, rows):
    tables.append({"title": title, "note": note, "columns": columns, "rows": rows})


# --- 1. verify_email: classification across edge cases (instant) ---
emails_in = ["owner@joesplumbing.com", "info@acme.com", "jane.doe@gmail.com", "sales@company.co",
             "test@mailinator.com", "a+newsletter@corp.io", "josé@example.com", "用户@例子.公司",
             "notanemail", "x@sub.domain.co.uk", "CEO@Startup.IO", "  spaced@x.com  ", "a@b"]
rows = []
for e in emails_in:
    try:
        v = verify_email(e)
        rows.append([e, v.get("valid_syntax"), v.get("domain"), v.get("is_role"),
                     v.get("is_freemail"), v.get("is_disposable"), v.get("has_alias")])
    except Exception as ex:
        rows.append([e, "EXCEPTION", str(ex)[:40], "", "", "", ""])
add("verify_email", "email classification — watch the IDN/unicode, malformed, and whitespace rows",
    ["input", "valid_syntax", "domain", "is_role", "is_freemail", "is_disposable", "has_alias"], rows)

# --- 2. phones(): false-positive bait (instant) ---
phone_in = ["Call us at (614) 837-3280 today", "Order #12345678901234 shipped",
            "ISBN 978-3-16-148410-0", "Resolution 1920 x 1080 pixels", "Call 1-800-FLOWERS now",
            "UK office +44 20 7946 0958", "India +91 98765 43210", "Fake (555) 555-5555 placeholder",
            "Text 415.555.1234 or 415-555-1234", "Card 4111 1111 1111 1111", "Meeting 2024 12 25 09 00"]
add("extract.phones()", "what pith pulls as phone numbers from raw text — false positives / dropped intl = data-quality faults",
    ["input text", "phones() output"], [[s, json.dumps(phones(s))] for s in phone_in])

# --- 3. emails(): false-positive bait (instant) ---
email_in = ["Reach jane@acme.com or bob@acme.com", "Logo at logo@2x.png in assets",
            "Runtime react@18.2.0 installed", "Cron @reboot runs the job", "Follow @company on twitter",
            "Price 5.00@night per room", "email hidden: name [at] domain [dot] com"]
add("extract.emails()", "false-positive bait for email extraction",
    ["input text", "emails() output"], [[s, json.dumps(emails(s))] for s in email_in])

# --- 4. socials(): profile vs non-profile ---
social_in = ['<a href="https://facebook.com/JoesPlumbing">fb</a>',
             '<a href="https://facebook.com/sharer.php?u=x">share</a>',
             '<a href="https://twitter.com/intent/tweet">tweet</a>',
             '<a href="https://www.linkedin.com/company/acme">li</a>',
             '<a href="https://instagram.com/joes.plumbing">ig</a>']
add("extract.socials()", "should keep real profile URLs, drop share/intent links",
    ["input html", "socials() output"], [[s[:52], json.dumps(socials(s))] for s in social_in])

# --- 5. Extractor.extract on real pages (live) ---
urls = ["https://example.com", "https://www.python.org", "https://news.ycombinator.com",
        "https://httpbin.org/html", "https://this-domain-does-not-exist-pith.invalid"]
rows = []
out = Extractor().extract(urls, concurrency=4)
for r in out.results:
    body = r.full_content or (r.excerpts[0] if r.excerpts else "")
    rows.append([r.url, (r.title or "")[:38], len(r.emails), len(r.phones), len(r.socials),
                 len(r.structured), len(body)])
for e in out.errors:
    rows.append([str(e)[:46], "ERROR", "", "", "", "", ""])
add("Extractor.extract (live)", "real page extraction — structured-data counts + content length; note the .invalid failure row",
    ["url", "title", "emails", "phones", "socials", "structured", "chars"], rows)

# --- 6. website_intel grades (live) ---
rows = []
for u in ["https://example.com", "https://www.python.org", "https://wordpress.org"]:
    try:
        a = website_intel(u)
        rows.append([a["domain"], a["modernness_grade"], a["modernness_score"], a["builder"],
                     a["responsive"], a["https"], a["domain_age_years"]])
    except Exception as ex:
        rows.append([u, "ERR", str(ex)[:30], "", "", "", ""])
add("website_intel (live)", "tech-stack + modernness grade", ["domain", "grade", "score", "builder", "responsive", "https", "age_yrs"], rows)

# --- 7. directory_search (live) ---
try:
    biz = directory_search("plumbers", "Tulsa, OK", limit=8)
    rows = [[b["name"][:34], b["phone"], (b.get("website", "") or "(none)")[:40], b.get("address", "")[:38]] for b in biz]
except Exception as ex:
    rows = [["ERROR", str(ex)[:50], "", ""]]
add("directory_search (live)", "YellowPages + SuperPages business list, deduped", ["name", "phone", "website", "address"], rows)

# --- 8. enumerate_profiles (live) ---
try:
    profs = enumerate_profiles("torvalds", persona="technical")
    rows = [[p["site"], p["kind"], p["value"], p["url"][:46]] for p in profs]
except Exception as ex:
    rows = [["ERROR", str(ex)[:50], "", ""]]
add("enumerate_profiles (live)", "OSINT profile enumeration for handle 'torvalds' — EXISTENCE only, not identity-verified (collisions possible)",
    ["site", "kind", "value", "url"], rows)

# --- 9. gravatar email->accounts pivot (live) ---
rows = []
for e in ["beau@dentedreality.com.au", "nobody-xyz-notreal@example.com"]:
    g = gravatar_profile(e)
    if g.get("exists"):
        rows.append([e, g["display_name"], g.get("location") or "", g["profile_url"],
                     ", ".join(a["site"] for a in g["accounts"])])
    else:
        rows.append([e, "NO PUBLIC PROFILE", "", "", ""])
add("gravatar (live) — email→accounts", "the best legal email→accounts pivot: a public Gravatar hands back linked profiles",
    ["email", "name", "location", "profile_url", "linked_accounts"], rows)

# --- 10. phone_intel (offline, deterministic) ---
phone_cases = [("+44 20 7946 0958", None), ("(212) 867-5309", None), ("+91 98765 43210", None),
               ("+1 800 555 0100", None), ("+61 2 9374 4000", None), ("notaphone", None)]
rows = []
for n, reg in phone_cases:
    d = phone_intel(n, reg)
    rows.append([n, d["valid"], d.get("region"), d.get("line_type"), d.get("location") or "", d.get("e164") or ""])
add("phone_intel (offline)", "region · line-type (mobile/landline/toll-free) · E.164 on any number — no lookups, no cost",
    ["input", "valid", "region", "line_type", "location", "e164"], rows)

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>pith — data tables</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,900&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
 :root{--paper:#faf8f4;--ink:#211c16;--dim:#8a8074;--line:#e4ddcf;--ox:#8b2b2b;--warn:#9a6a1a;--panel:#f2ede3}
 *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font-family:"JetBrains Mono",monospace;font-size:12.5px}
 header{padding:22px 30px;border-bottom:2px solid var(--ink)}
 header h1{margin:0;font-family:"Fraunces",serif;font-weight:900;font-size:32px}
 header h1 .d{color:var(--ox)} header .s{color:var(--dim);font-family:"Fraunces",serif;font-style:italic}
 .wrap{padding:14px 30px 60px}
 section{margin:26px 0}
 h2{font-family:"Fraunces",serif;font-weight:600;font-size:20px;margin:0 0 2px;border-left:3px solid var(--ox);padding-left:10px}
 .note{color:var(--dim);margin:0 0 10px;padding-left:13px;font-size:12px}
 table{border-collapse:collapse;width:100%;background:#fff;border:1px solid var(--line)}
 th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}
 th{background:var(--panel);color:var(--dim);text-transform:uppercase;letter-spacing:1px;font-size:10px;cursor:pointer;user-select:none;position:sticky;top:0}
 th:hover{color:var(--ox)} tr:hover td{background:#fbf8f2}
 td.b-true{color:#4d6b45;font-weight:700} td.b-false{color:var(--dim)} td.err{color:var(--ox);font-weight:700}
 td.empty{color:var(--warn)} .count{color:var(--dim);font-weight:400;font-size:13px;font-family:"JetBrains Mono"}
</style></head><body>
<header><h1>pith<span class="d">.</span> data tables</h1><span class="s">the actual output — normal and edge cases</span></header>
<div class="wrap" id="wrap"></div>
<script>
const TABLES=__DATA__;
const wrap=document.getElementById('wrap');
function cell(v){
  const td=document.createElement('td');
  if(v===true){td.textContent='true';td.className='b-true';}
  else if(v===false){td.textContent='false';td.className='b-false';}
  else if(v===null||v===''||v==='[]'){td.textContent=(v==='[]'?'[]':'—');td.className='empty';}
  else if(v==='ERROR'||v==='EXCEPTION'||v==='ERR'){td.textContent=v;td.className='err';}
  else td.textContent=String(v);
  return td;
}
TABLES.forEach(t=>{
  const sec=document.createElement('section');
  const h=document.createElement('h2');h.textContent=t.title;
  h.innerHTML+=` <span class="count">· ${t.rows.length} rows</span>`;
  const p=document.createElement('p');p.className='note';p.textContent=t.note;
  const tbl=document.createElement('table');
  const thead=document.createElement('thead');const htr=document.createElement('tr');
  t.columns.forEach((c,ci)=>{const th=document.createElement('th');th.textContent=c;
    th.onclick=()=>sortBy(tbl,ci);htr.appendChild(th);});
  thead.appendChild(htr);tbl.appendChild(thead);
  const tb=document.createElement('tbody');
  t.rows.forEach(r=>{const tr=document.createElement('tr');r.forEach(v=>tr.appendChild(cell(v)));tb.appendChild(tr);});
  tbl.appendChild(tb);
  sec.append(h,p,tbl);wrap.appendChild(sec);
});
function sortBy(tbl,ci){
  const tb=tbl.querySelector('tbody');const rows=[...tb.rows];
  const asc=tbl.dataset.sc!=ci+'a';
  rows.sort((a,b)=>{const x=a.cells[ci].textContent,y=b.cells[ci].textContent;
    const nx=parseFloat(x),ny=parseFloat(y);
    if(!isNaN(nx)&&!isNaN(ny))return asc?nx-ny:ny-nx;
    return asc?x.localeCompare(y):y.localeCompare(x);});
  tbl.dataset.sc=ci+(asc?'a':'d');rows.forEach(r=>tb.appendChild(r));
}
</script></body></html>"""

(HERE / "index.html").write_text(TEMPLATE.replace("__DATA__", json.dumps(tables)))
print(f"wrote {HERE/'index.html'} — {len(tables)} tables, {sum(len(t['rows']) for t in tables)} rows")
