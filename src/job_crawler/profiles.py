"""Public company information and evidence-bearing IT classification."""
from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .details import structured_objects

TECH = re.compile(r"software|phần mềm|lập trình|information technology|it services|"
                  r"công nghệ thông tin|web services|fintech|game development|"
                  r"dịch vụ công nghệ|saas|trí tuệ nhân tạo|artificial intelligence", re.I)


def classify(profile: dict, *, has_it_jobs: bool = False) -> tuple[str, str | None]:
    for field in ("industry", "name", "description"):
        match = TECH.search(profile.get(field) or "")
        if match:
            return "technology", f"{field}: {match.group(0)}"
    if has_it_jobs:
        return "it_department", "observed IT job linked to this source profile"
    if profile.get("source") in ("itviec", "topdev"):
        return "it_department", f"listed on specialist IT directory: {profile['source']}"
    return "unknown", None


def _label(soup, label: str):
    node = soup.find(string=re.compile(r"^\s*(?:" + label + r")\s*:?\s*$", re.I))
    if node and node.parent:
        sibling = node.parent.find_next_sibling()
        if sibling:
            return sibling.get_text(" ", strip=True) or None
    return None


def parse(html: str, source: str, base: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.h1 and not (source == "topdev" and base.get("name")):
        raise ValueError("Company page has no primary name")
    result = {"name": soup.h1.get_text(" ", strip=True) if soup.h1 else base["name"]}
    if len(result["name"]) > 300:
        raise ValueError("Company name exceeds contract length")
    for field, label in {"company_type": "Company type|Mô hình công ty",
                         "country": "Country|Quốc gia", "working_days": "Working days|Thời gian làm việc",
                         "overtime": "Overtime policy|Làm việc ngoài giờ",
                         "industry": "Company industry|Lĩnh vực công ty|Ngành nghề(?: kinh doanh)?",
                         "size": "Company size|Quy mô(?: công ty)?"}.items():
        result[field] = _label(soup, label) or base.get(field)
    overview = soup.select_one("#section-introduce")
    if source == "topdev":
        about = soup.find(["h2", "h3"], string=re.compile(r"^\s*About Us\s*$", re.I))
        overview = about.find_parent("section") if about else None
        if not overview and about:
            overview = about.parent
    if not overview:
        heading = soup.find(string=re.compile(r"^\s*(Company overview|Giới thiệu công ty)\s*$", re.I))
        overview = heading.parent.parent if heading and heading.parent else None
    result["description"] = (overview.get_text("\n", strip=True)[:20000] if overview
                             else base.get("description"))
    addresses = [n.get("data-location") or n.get_text(" ", strip=True)
                 for n in soup.select("[data-location], .box-body__address--text")]
    result["address"] = "\n".join(dict.fromkeys(addresses)) or _label(soup, "Địa chỉ|Address")
    public_links = []
    for node in soup.select("[data-redirect-url-url-value]"):
        url = node.get("data-redirect-url-url-value", "").strip()
        if urlparse(url).scheme in ("http", "https"):
            public_links.append({"label": node.get_text(" ", strip=True), "url": url})
            if "website" in node.get_text().lower():
                result["website"] = url
    # Only the employer header and introduction; never include the board's footer contacts.
    scopes = [n for n in (soup.select_one(".company-detail-overview"), overview) if n]
    if source == "topdev":
        # Employer detail lives inside main; the board's contacts are in footer.
        employer_main = soup.select_one("main")
        if employer_main:
            scopes.append(employer_main)
    for scope in scopes:
        for a in scope.select("a[href]"):
            url = a.get("href", "").strip()
            if urlparse(url).scheme not in ("http", "https", "mailto", "tel"):
                continue
            host = urlparse(url).hostname or ""
            if host.endswith(("topcv.vn", "itviec.com", "topdev.vn")):
                continue
            label = a.get_text(" ", strip=True)
            if not any(link["url"] == url for link in public_links):
                public_links.append({"label": label[:160], "url": url})
            if "website" in label.lower() or (url in label and host and "website" not in result):
                result["website"] = url
    for org in structured_objects(soup):
        if org.get("@type") in ("Organization", "Corporation"):
            if isinstance(org.get("url"), str) and urlparse(org["url"]).hostname not in ("itviec.com", "topdev.vn", "www.topcv.vn"):
                result.setdefault("website", org["url"])
            logo = org.get("logo")
            result["logo_url"] = logo if isinstance(logo, str) else (logo or {}).get("url")
    result["public_links"] = json.dumps(public_links, ensure_ascii=False)
    skills_heading = soup.find(string=re.compile(r"^\s*(Our key skills|Kỹ năng chính)\s*$", re.I))
    skills_scope = skills_heading.parent.parent if skills_heading and skills_heading.parent else None
    stack = list(dict.fromkeys(n.get_text(" ", strip=True) for n in skills_scope.select('a.itag'))) if skills_scope else []
    result["tech_stack"] = json.dumps(stack, ensure_ascii=False)
    benefits = soup.find(string=re.compile(r"^\s*(Why you'll love working here|Phúc lợi)\s*$", re.I))
    result["benefits"] = benefits.parent.parent.get_text("\n", strip=True)[:12000] if benefits and benefits.parent else None
    return {**base, **result}
