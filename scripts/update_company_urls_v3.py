"""Extract company profile URLs từ listing HTML và cập nhật companies table.
Version 3: Correct regex escaping for TopDev RSC JSON.
"""
import re
import sqlite3
from pathlib import Path

DB = Path('data/job_crawler.db')
conn = sqlite3.connect(DB)
c = conn.cursor()

# =====================================================
# 1. TopDev
# =====================================================
with open('recon/topdev_render.html', 'r') as f:
    html = f.read()

# Extract company profile URLs: https://topdev.vn/companies/{slug}-{id}
td_url_by_id = {}
for m in re.finditer(r'https://topdev\.vn/companies/([a-z0-9-]+)-(\d+)', html):
    td_url_by_id[m.group(2)] = m.group(0)
print(f"TopDev: Found {len(td_url_by_id)} unique company profile URLs")

# Extract company data from RSC JSON
# The HTML contains sequences like: \\\"id\\\":97096,\\\"display_name\\\":\\\"CÔNG TY...\"
# In raw Python string, this appears as: \\"id\\":97096,\\"display_name\\":\\"CÔNG TY...\"
company_data = re.findall(r'\\"id\\":(\d+),\\"display_name\\":\\"((?:[^\\]|\\.)+)\\"', html)
print(f"TopDev: Found {len(company_data)} company data entries from RSC JSON")

# Create mapping: company_id -> (name, company_url)
td_id_to_info = {}
for cid, name in company_data:
    if cid in td_url_by_id:
        td_id_to_info[cid] = (name, td_url_by_id[cid])

print(f"TopDev: Matched {len(td_id_to_info)} company ID -> URL")

# Update TopDev companies
updated_td = 0
for company in c.execute('SELECT company, detail_url FROM companies WHERE source="topdev"').fetchall():
    cname = company[0]
    for cid, (html_name, url) in td_id_to_info.items():
        if cname == html_name or cname.lower() == html_name.lower():
            c.execute('UPDATE companies SET detail_url=? WHERE source="topdev" AND company=?', (url, cname))
            updated_td += 1
            break

print(f"TopDev: Updated {updated_td} companies with company page URL")

# =====================================================
# 2. TopCV
# =====================================================
with open('recon/topcv_chrome.html', 'r') as f:
    html = f.read()

# Extract company profile URLs: /cong-ty/{slug}/{id}.html
tc_url_by_id = {}
for m in re.finditer(r'href="(?:https://www\.topcv\.vn)?/cong-ty/([a-z0-9-]+)/(\d+)\.html', html):
    tc_url_by_id[m.group(2)] = f"https://www.topcv.vn/cong-ty/{m.group(1)}/{m.group(2)}.html"

# Extract company names from HTML
tc_name_by_id = {}
for m in re.finditer(r'class="company[^"]*"[^>]*>([^<]+)<', html):
    name = m.group(1).strip()
    if name and len(name) > 3:
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
    cname_lower = cname.lower().strip()

    for cid, html_name in tc_name_by_id.items():
        if cid in tc_url_by_id:
            html_lower = html_name.lower().strip()
            if cname_lower == html_lower:
                c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url_by_id[cid], cname))
                updated_tc += 1
                break
            elif len(cname_lower) > 10 and len(html_lower) > 10:
                if cname_lower in html_lower or html_lower in cname_lower:
                    c.execute('UPDATE companies SET detail_url=? WHERE source="topcv" AND company=?', (tc_url_by_id[cid], cname))
                    updated_tc += 1
                    break

print(f"TopCV: Updated {updated_tc} companies with detail_url")

conn.commit()

# =====================================================
# Final Status
# =====================================================
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

print("\n=== Sample Companies with URLs ===")
c.execute('SELECT source, company, detail_url, bucket FROM companies WHERE source="topdev" AND detail_url IS NOT NULL LIMIT 5')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} -> {row[2]} (bucket: {row[3]})")

c.execute('SELECT source, company, detail_url, bucket FROM companies WHERE source="topcv" AND detail_url IS NOT NULL LIMIT 5')
for row in c.fetchall():
    print(f"  {row[0]}: {row[1]} -> {row[2]} (bucket: {row[3]})")

conn.close()
