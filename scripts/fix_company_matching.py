"""Fix TopDev company matching + find more TopCV company URLs."""
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.job_crawler.company_enrich import (
    fetch_topcv_size, parse_size_range, bucket_for, upsert_company, ensure_company_tables
)

DB = Path('data/job_crawler.db')
conn = sqlite3.connect(DB)
c = conn.cursor()

# =====================================================
# 1. TopDev: Fix matching by cleaning extracted names
# =====================================================
with open('recon/topdev_render.html', 'r') as f:
    html = f.read()

# Find company objects with detail_url + display_name + company_size
# Pattern in RSC JSON: detail_url":"https://topdev.vn/companies/...", display_name":"XXX", company_size":"XXX"
td_companies = {}

# Find all company objects by detail_url
for m in re.finditer(r'detail_url\\":\\"(https://topdev\.vn/companies/[^\\]+)\\"', html):
    url = m.group(1)
    # Extract company ID from URL
    id_m = re.search(r'-(\d+)$', url)
    cid = id_m.group(1) if id_m else None
    
    # Get context around this detail_url (the company object)
    chunk = html[m.start()-2000:m.start()+2000]
    
    # Find display_name in this chunk
    name_m = re.search(r'display_name\\":\\"((?:[^\\]|\\.)+?)\\"', chunk)
    size_m = re.search(r'company_size\\":\\"((?:[^\\]|\\.)*?)\\"', chunk)
    
    name = name_m.group(1) if name_m else None
    size = size_m.group(1) if size_m else None
    
    if name and url not in td_companies:
        td_companies[url] = {'name': name, 'size_raw': size or ''}

print(f"TopDev: Extracted {len(td_companies)} companies from listing HTML")

# Build lookup: normalize name for matching
def normalize_name(n):
    return re.sub(r'[^a-z0-9]+', '', n.lower().strip())

td_lookup = {}
for url, data in td_companies.items():
    if data['size_raw']:
        norm = normalize_name(data['name'])
        td_lookup[norm] = (url, data)

# Get DB companies
db_companies = c.execute('SELECT company FROM companies WHERE source="topdev"').fetchall()
db_lookup = {normalize_name(row[0]): row[0] for row in db_companies}

updated_td = 0
for norm_name, db_name in db_lookup.items():
    if norm_name in td_lookup:
        url, data = td_lookup[norm_name]
        smin, smax = parse_size_range(data['size_raw'])
        bucket = bucket_for(smin, smax)
        c.execute('''UPDATE companies SET size_raw=?, size_min=?, size_max=?, bucket=?, detail_url=?
                     WHERE source="topdev" AND company=?''',
                  (data['size_raw'], smin, smax, bucket, url, db_name))
        updated_td += 1
        print(f"  ✓ {db_name}: {data['size_raw']} -> {bucket}")

print(f"TopDev: Updated {updated_td} companies")

# =====================================================
# 2. TopCV: Find more company URLs from listing HTML
# =====================================================
with open('recon/topcv_chrome.html', 'r') as f:
    html = f.read()

# Find company links: <a class="company" href="/cong-ty/slug/ID.html">Name</a>
tc_name_to_url = {}
for m in re.finditer(r'<a[^>]*class="company"[^>]*href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html"[^>]*>([^<]+)<', html):
    slug, cid, name = m.group(1), m.group(2), m.group(3).strip()
    if name and cid and len(name) > 3:
        tc_name_to_url[name] = f"https://www.topcv.vn/cong-ty/{slug}/{cid}.html"

# Also try: any href with /cong-ty/ followed by company name
for m in re.finditer(r'href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html"[^>]*>([^<]+)<', html):
    slug, cid, name = m.group(1), m.group(2), m.group(3).strip()
    if name and cid and len(name) > 3:
        tc_name_to_url[name] = f"https://www.topcv.vn/cong-ty/{slug}/{cid}.html"

print(f"\nTopCV: Found {len(tc_name_to_url)} company name -> URL mappings")

# Match with DB companies missing detail_url
c.execute('''SELECT company FROM companies 
             WHERE source="topcv" AND (detail_url IS NULL OR detail_url = "")''')
missing_companies = [row[0] for row in c.fetchall()]

matched = 0
tc_lookup = {normalize_name(k): v for k, v in tc_name_to_url.items()}
db_missing_lookup = {normalize_name(n): n for n in missing_companies}

for norm_name, db_name in db_missing_lookup.items():
    if norm_name in tc_lookup:
        c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', 
                  (tc_lookup[norm_name], db_name))
        matched += 1

print(f"TopCV: Matched {matched} additional companies")

conn.commit()

# =====================================================
# 3. Re-run TopCV enrichment for newly matched
# =====================================================
ensure_company_tables(conn)

c.execute('''SELECT company, detail_url FROM companies
             WHERE source="topcv" AND detail_url IS NOT NULL AND detail_url != ""
             AND (bucket IS NULL OR bucket = "")''')
topcv_companies = c.fetchall()
print(f"\nTopCV: {len(topcv_companies)} companies need enrichment")

enriched_tc = 0
for company_name, detail_url in topcv_companies:
    try:
        size_raw = fetch_topcv_size(detail_url)
        if size_raw:
            smin, smax = parse_size_range(size_raw)
            bucket = bucket_for(smin, smax)
            upsert_company(conn, 'topcv', company_name, detail_url, size_raw, smin, smax)
            enriched_tc += 1
            print(f"  ✓ {company_name}: {size_raw} -> {bucket}")
        else:
            print(f"  - {company_name}: no size found")
    except Exception as e:
        print(f"  ✗ {company_name}: {e}")

print(f"TopCV: Enriched {enriched_tc} additional companies")
conn.commit()

# =====================================================
# Final Status
# =====================================================
print("\n=== Final Status ===")
c.execute('''
    SELECT source,
           COUNT(*) as total,
           SUM(CASE WHEN bucket IS NOT NULL AND bucket != "" THEN 1 ELSE 0 END) as has_bucket,
           SUM(CASE WHEN detail_url IS NOT NULL AND detail_url != "" THEN 1 ELSE 0 END) as has_url
    FROM companies GROUP BY source
''')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} total, {row[2]} with_bucket, {row[3]} with_url")

print("\n=== Jobs with company_size ===")
c.execute('''
    SELECT j.source, c.bucket, COUNT(*)
    FROM jobs j LEFT JOIN companies c ON j.company = c.company AND j.source = c.source
    WHERE c.bucket IS NOT NULL AND c.bucket != ""
    GROUP BY j.source, c.bucket
''')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} = {row[2]} jobs")

conn.close()