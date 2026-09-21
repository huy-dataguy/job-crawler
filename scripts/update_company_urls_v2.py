"""Extract company profile URLs từ listing HTML và cập nhật companies table.
Version 2: Match by company ID from URL slug, not by name.
"""
import re
import sqlite3
from pathlib import Path

DB = Path('data/job_crawler.db')
conn = sqlite3.connect(DB)
c = conn.cursor()

# 1. Extract TopDev company URLs from listing HTML
with open('recon/topdev_render.html', 'r') as f:
    html = f.read()

# Find company profile URLs: https://topdev.vn/companies/{slug}-{id}
# The ID at the end is the company ID
td_url_by_id = {}
for m in re.finditer(r'https://topdev\.vn/companies/([a-z0-9-]+)-(\d+)', html):
    slug, company_id = m.group(1), m.group(2)
    full_url = m.group(0)
    td_url_by_id[company_id] = full_url

print(f"TopDev: Found {len(td_url_by_id)} unique company URLs")

# Extract company data from RSC JSON (escaped quotes)
# Pattern: \"id\":XXX,\"display_name\":\"XXX\"
company_data = re.findall(r'\\"id\\":(\d+),\\"display_name\\":\\"([^\\]+)\\"', html)
print(f"TopDev: Found {len(company_data)} company data entries")

# Create mapping: company_id -> company_url
td_id_to_url = {}
for cid, name in company_data:
    if cid in td_url_by_id:
        td_id_to_url[cid] = (name, td_url_by_id[cid])

print(f"TopDev: Matched {len(td_id_to_url)} company ID -> URL")

# Now we need to find the company ID for each company in the DB
# The company ID is embedded in the job URL: /detail-jobs/...-{job_id}
# But we need the COMPANY ID, not job ID

# Let's look at the job data to find company IDs
# In the listing JSON, each job has: "owned_id":XXX (company ID)
owned_ids = re.findall(r'\\\\\"owned_id\\\\\":(\d+)', html)
print(f"TopDev: Found {len(owned_ids)} owned_id entries")

# Create mapping: company_name -> company_id from owned_id + display_name
# We need to match owned_id to display_name
# Pattern: "owned_id":XXX followed by "company":{"id":XXX,...}
company_owned = re.findall(r'\\\\\"owned_id\\\\\":(\d+),\\\\\"company\\\\\":\{\\\\\"id\\\\\":(\d+)', html)
print(f"TopDev: Found {len(company_owned)} owned_id -> company_id pairs")

# Update TopDev companies: match by company name
updated_td = 0
for company in c.execute('SELECT company, detail_url FROM companies WHERE source="topdev"').fetchall():
    cname, current_url = company[0], company[1]

    # Find this company in the extracted data
    for cid, (html_name, url) in td_id_to_url.items():
        if cname == html_name or cname.lower() == html_name.lower():
            # Update with company page URL (not job detail URL)
            if 'companies' in url:  # Only update if it's a company URL
                c.execute('UPDATE companies SET detail_url=? WHERE source="topdev" AND company=?', (url, cname))
                updated_td += 1
                break

print(f"TopDev: Updated {updated_td} companies with company page URL")

# 2. Extract TopCV company URLs from listing HTML
with open('recon/topcv_chrome.html', 'r') as f:
    html = f.read()

# Pattern: /cong-ty/{slug}/{id}.html
tc_url_by_id = {}
tc_name_by_id = {}
for m in re.finditer(r'href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html', html):
    slug, company_id = m.group(1), m.group(2)
    full_url = f"https://www.topcv.vn/cong-ty/{slug}/{company_id}.html"
    tc_url_by_id[company_id] = full_url

# Extract company names from the HTML
# Pattern: class="company-name">Name</span> or similar
for m in re.finditer(r'class="company[^"]*"[^>]*>([^<]+)<', html):
    name = m.group(1).strip()
    if name and len(name) > 3:
        # Try to find the associated company ID
        # Look for nearby href with /cong-ty/
        start = max(0, m.start() - 500)
        end = min(len(html), m.end() + 500)
        context = html[start:end]
        id_match = re.search(r'/cong-ty/[a-z0-9-]+/(\d+)\.html', context)
        if id_match:
            tc_name_by_id[id_match.group(1)] = name

print(f"\nTopCV: Found {len(tc_url_by_id)} unique company URLs")
print(f"TopCV: Found {len(tc_name_by_id)} company name -> ID mappings")

# Update TopCV companies
updated_tc = 0
for company in c.execute('SELECT company FROM companies WHERE source="topcv" AND (detail_url IS NULL OR detail_url="")').fetchall():
    cname = company[0]

    # Try to find this company in the extracted data
    for cid, html_name in tc_name_by_id.items():
        if cid in tc_url_by_id:
            if cname == html_name or cname.lower() == html_name.lower():
                c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url_by_id[cid], cname))
                updated_tc += 1
                break
            # Try partial match
            elif len(cname) > 10 and len(html_name) > 10:
                if cname.lower() in html_name.lower() or html_name.lower() in cname.lower():
                    c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url_by_id[cid], cname))
                    updated_tc += 1
                    break

print(f"TopCV: Updated {updated_tc} companies with detail_url")

conn.commit()

# Final status
print("\n=== Final Status ===")
c.execute('''
    SELECT source,
           COUNT(*) as total,
           SUM(CASE WHEN detail_url IS NULL OR detail_url = '' THEN 1 ELSE 0 END) as missing_url,
           SUM(CASE WHEN bucket IS NOT NULL THEN 1 ELSE 0 END) as has_bucket
    FROM companies GROUP BY source
''')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} total, {row[2]} missing_url, {row[3]} has_bucket")

# Show some examples
print("\n=== Sample Companies with URLs ===")
c.execute('SELECT source, company, detail_url, bucket FROM companies WHERE detail_url IS NOT NULL AND detail_url != "" LIMIT 10')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} -> {row[2]} (bucket: {row[3]})")

conn.close()
