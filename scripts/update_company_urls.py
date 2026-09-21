"""Extract company profile URLs từ listing HTML và cập nhật companies table."""
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
td_company_urls = {}
for m in re.finditer(r'https://topdev\.vn/companies/([a-z0-9-]+)-(\d+)', html):
    company_id = m.group(2)
    full_url = m.group(0)
    td_company_urls[company_id] = full_url

print(f"TopDev: Found {len(td_company_urls)} unique company URLs")

# Extract company data from RSC JSON (escaped quotes): \"id\":XXX,\"display_name\":\"XXX\"
company_data = re.findall(r'\\?"id\\?":(\d+),\\?"display_name\\?":\\?"([^\\"]+)\\?"', html)
# Also try non-escaped version
company_data += re.findall(r'"id":(\d+),"display_name":"([^"]+)"', html)
# Deduplicate
seen = set()
unique_data = []
for cid, name in company_data:
    if cid not in seen:
        seen.add(cid)
        unique_data.append((cid, name))
company_data = unique_data
print(f"TopDev: Found {len(company_data)} company data entries")

# Create mapping: display_name -> company_url
td_name_to_url = {}
for cid, name in company_data:
    if cid in td_company_urls:
        td_name_to_url[name] = td_company_urls[cid]

# Update TopDev companies
updated_td = 0
for company_name, url in td_name_to_url.items():
    c.execute('''
        UPDATE companies
        SET detail_url = ?
        WHERE source = 'topdev' AND company = ? AND (detail_url IS NULL OR detail_url = '')
    ''', (url, company_name))
    if c.rowcount > 0:
        updated_td += 1

print(f"TopDev: Updated {updated_td} companies with detail_url")

# 2. Extract TopCV company URLs from listing HTML
with open('recon/topcv_chrome.html', 'r') as f:
    html = f.read()

# Pattern: /cong-ty/{slug}/{id}.html inside href
tc_company_urls = {}
for m in re.finditer(r'href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html', html):
    slug, company_id = m.group(1), m.group(2)
    full_url = f"https://www.topcv.vn/cong-ty/{slug}/{company_id}.html"
    tc_company_urls[company_id] = full_url

print(f"\nTopCV: Found {len(tc_company_urls)} unique company URLs")

# TopCV: company names are in <a class="company" ...>Name</a>
# The link contains the company ID. Match by company name from card context.
# Extract: card links with company name
tc_name_to_url = {}

# Try multiple patterns to extract company name + URL
# Pattern 1: href="/cong-ty/slug/ID.html">Company Name</a>
for m in re.finditer(r'href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html"[^>]*>([^<]+)<', html):
    slug, company_id, name = m.group(1), m.group(2), m.group(3).strip()
    if name and company_id and len(name) > 3:
        tc_name_to_url[name] = f"https://www.topcv.vn/cong-ty/{slug}/{company_id}.html"

# Pattern 2: <a class="company" ... href="...">Name</a>
for m in re.finditer(r'<a[^>]*class="company"[^>]*href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html"[^>]*>([^<]+)<', html):
    slug, company_id, name = m.group(1), m.group(2), m.group(3).strip()
    if name and company_id and len(name) > 3:
        tc_name_to_url[name] = f"https://www.topcv.vn/cong-ty/{slug}/{company_id}.html"

# Pattern 3: data-company-name="..." or similar attributes
for m in re.finditer(r'data-company-name="([^"]+)"[^>]*href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html', html):
    name, slug, company_id = m.group(1).strip(), m.group(2), m.group(3)
    if name and company_id:
        tc_name_to_url[name] = f"https://www.topcv.vn/cong-ty/{slug}/{company_id}.html"

print(f"TopCV: Matched {len(tc_name_to_url)} company name -> URL mappings")

# Update TopCV companies
updated_tc = 0
matched = 0
# Get all unmatched TopCV companies
unmatched = c.execute('SELECT company FROM companies WHERE source="topcv" AND (detail_url IS NULL OR detail_url="")').fetchall()

for company in unmatched:
    cname = company[0]
    cname_lower = cname.lower().strip()

    # Try exact match (case-insensitive)
    found = False
    for tc_name, tc_url in tc_name_to_url.items():
        if cname_lower == tc_name.lower().strip():
            c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url, cname))
            updated_tc += 1
            matched += 1
            found = True
            break

    if found:
        continue

    # Try partial match (name contains slug or vice versa)
    for tc_name, tc_url in tc_name_to_url.items():
        tc_lower = tc_name.lower().strip()
        # Check if one contains the other (at least 10 chars)
        if len(cname_lower) >= 10 and len(tc_lower) >= 10:
            if cname_lower in tc_lower or tc_lower in cname_lower:
                c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url, cname))
                updated_tc += 1
                matched += 1
                found = True
                break

print(f"TopCV: Updated {updated_tc} companies with detail_url (matched {matched})")

# 3. For remaining unmatched TopCV companies, try to construct URL from company name
# TopCV URL pattern: /cong-ty/{slug}/{id}.html
# The slug is derived from company name (Vietnamese diacritics removed, lowercase, hyphens)
# But we need the company ID which is only available from the listing page

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

conn.close()
