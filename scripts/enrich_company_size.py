"""Directly extract company_size from TopDev listing RSC JSON and update DB.
Then run enrichment for TopCV companies that have detail_url."""
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
# 1. TopDev: Extract company_size from listing RSC JSON
# =====================================================
with open('recon/topdev_render.html', 'r') as f:
    html = f.read()

# Strategy: find each company object by owned_id marker, then extract display_name + company_size + detail_url
# The RSC JSON has patterns like:
#   owned_id\":97096,\"company\":{\"id\":97096,\"display_name\":\"XXX\",...,\"company_size\":\"XXX\",...}
# We find company_size directly from the company object

# Find company detail_urls with their IDs
td_url_by_id = {}
for m in re.finditer(r'detail_url\\":\\"(https://topdev\.vn/companies/[^\\]+)\\"', html):
    url = m.group(1)
    # Extract company ID from URL
    id_m = re.search(r'-(\d+)$', url)
    if id_m:
        td_url_by_id[id_m.group(1)] = url

# Find company data: display_name + company_size pairs
# These appear in the "company" object within each job listing
# Pattern: "display_name":"XXX",...,"company_size":"XXX"
# We'll extract by finding company objects

td_companies = {}  # company_url -> {name, size_raw}

# Find company objects by searching for detail_url + nearby company_size
# Each company in the listing has detail_url pointing to /companies/...
for m in re.finditer(r'detail_url\\":\\"(https://topdev\.vn/companies/[^\\]+)\\"', html):
    url = m.group(1)
    # Search forward for company_size within the same company object (within ~2000 chars)
    chunk = html[m.start():m.start()+3000]
    name_m = re.search(r'display_name\\":\\"((?:[^\\]|\\.)+)\\"', chunk)
    size_m = re.search(r'company_size\\":\\"((?:[^\\]|\\.)*)\\"', chunk)
    
    name = name_m.group(1) if name_m else None
    size = size_m.group(1) if size_m else None
    
    if name and url not in td_companies:
        td_companies[url] = {'name': name, 'size_raw': size or ''}

print(f"TopDev: Extracted {len(td_companies)} companies from listing HTML:")
updated_td = 0
for url, data in td_companies.items():
    if data['size_raw']:
        # Find this company in DB by name
        c.execute('SELECT company FROM companies WHERE source="topdev" AND company=?', (data['name'],))
        row = c.fetchone()
        if row:
            smin, smax = parse_size_range(data['size_raw'])
            bucket = bucket_for(smin, smax)
            c.execute('''UPDATE companies SET size_raw=?, size_min=?, size_max=?, bucket=?, detail_url=?
                         WHERE source="topdev" AND company=?''',
                      (data['size_raw'], smin, smax, bucket, url, data['name']))
            updated_td += 1
            print(f"  ✓ {data['name']}: {data['size_raw']} -> {bucket}")
        else:
            print(f"  ✗ {data['name']}: not in DB (size={data['size_raw']})")
    else:
        print(f"  - {data['name']}: no size data")

print(f"\nTopDev: Updated {updated_td} companies")

# =====================================================
# 2. TopCV: Run enrichment for companies with detail_url
# =====================================================
print("\n=== Running TopCV enrichment ===")
ensure_company_tables(conn)

c.execute('''SELECT company, detail_url FROM companies
             WHERE source="topcv" AND detail_url IS NOT NULL AND detail_url != ""
             AND (bucket IS NULL OR bucket = "")''')
topcv_companies = c.fetchall()
print(f"TopCV: {len(topcv_companies)} companies need enrichment")

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

print(f"\nTopCV: Enriched {enriched_tc} companies")

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

# Jobs with company_size
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
