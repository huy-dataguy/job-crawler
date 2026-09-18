"""Normalize dùng chung: tags sạch + năm kinh nghiệm → số."""
from __future__ import annotations

import json
import re

# Tag dạng "X năm kinh nghiệm…" là thông tin trùng với cột experience → loại khỏi tags
_EXP_TAG_RE = re.compile(
    r"^\s*(\d+\s*năm kinh nghiệm|không yêu cầu.*|trên \d+.*|dưới \d+.*|.*kinh nghiệm chuyên môn.*)\s*$",
    re.IGNORECASE,
)

_EXP_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*năm", re.IGNORECASE)


def clean_tags(raw: list[str]) -> list[str]:
    """Bỏ tag trùng experience, bỏ rỗng/trùng, giữ thứ tự."""
    out: list[str] = []
    for t in raw:
        t = re.sub(r"\s+", " ", (t or "").strip(" .,;"))
        if not t or len(t) < 2:
            continue
        if _EXP_TAG_RE.match(t):
            continue
        if t not in out:
            out.append(t)
    return out


def tags_json(raw: list[str]) -> str:
    return json.dumps(clean_tags(raw), ensure_ascii=False)


def parse_exp_min(text: str) -> float | None:
    """'2 năm' → 2.0; 'Không yêu cầu'/'Dưới 1 năm' → 0.0; 'Trên 5 năm' → 5.0; rỗng → None."""
    t = (text or "").strip().lower()
    if not t:
        return None
    if "không" in t or "dưới" in t or "fresher" in t or "intern" in t:
        return 0.0
    m = _EXP_NUM_RE.search(t)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def exp_bucket(exp_min: float | None) -> str:
    """Bucket hiển thị: '0' (fresher/không YC), '1'..'4', '5+'."""
    if exp_min is None:
        return ""
    if exp_min <= 0:
        return "0"
    if exp_min >= 5:
        return "5+"
    return str(int(exp_min))


# --- Phân loại IT & bóc kỹ năng IT --------------------------------------
# Canonical skill → alias match trong title/tags (lowercase, substring có ranh giới mềm)

IT_SKILLS: dict[str, list[str]] = {
    "Java": ["java"],
    "Python": ["python"],
    "Golang": ["golang", " go ", "golang,", "(go)"],
    "Node.js": ["node.js", "nodejs", "node js"],
    "PHP": ["php"],
    ".NET": [".net", "dotnet", "c#"],
    "C++": ["c++"],
    "Kotlin": ["kotlin"],
    "Swift": ["swift"],
    "Dart/Flutter": ["flutter", "dart"],
    "JavaScript": ["javascript", " js ", "/js", "js,"],
    "TypeScript": ["typescript"],
    "React": ["react", "reactjs", "nextjs", "next.js"],
    "Angular": ["angular"],
    "Vue": ["vue", "vuejs", "nuxt"],
    "Android": ["android"],
    "iOS": ["ios", "iphone"],
    "Backend": ["backend", "back-end", "back end"],
    "Frontend": ["frontend", "front-end", "front end"],
    "Fullstack": ["fullstack", "full-stack"],
    "API/Microservices": ["microservice", "restful", "rest api", "graphql"],
    "Spring": ["spring", "spring boot"],
    "Django": ["django"],
    "Laravel": ["laravel"],
    "DevOps": ["devops"],
    "Docker": ["docker"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws"],
    "Azure": ["azure"],
    "GCP": ["gcp", "google cloud"],
    "CI/CD": ["ci/cd", "cicd", "jenkins", "gitlab ci"],
    "Terraform": ["terraform"],
    "Linux": ["linux"],
    "SQL": ["sql", "mysql", "postgresql", "postgres", "oracle db", "mongodb"],
    "Data Engineer": ["data engineer", "etl", "data pipeline", "big data"],
    "Data Analyst": ["data analyst", "power bi", "powerbi", "tableau", "excel"],
    "Data Scientist": ["data scientist", "data science"],
    "AI/ML": ["machine learning", "deep learning", "artificial intelligence", " ai ", "ai,",
              "ai engineer", "llm", "data ai"],
    "Tester/QA": ["tester", "qa", "qc", "test case", "manual test", "automation test",
                  "selenium", "playwright", "cypress"],
    "Security": ["security", "devsecops", "penetration", "pentest", "soc ", "iso 27001"],
    "BA": ["business analyst", " ba ", "(ba)"],
    "Product Owner": ["product owner"],
    "Project Manager": ["project manager", "delivery manager"],
    "Scrum": ["scrum", "agile"],
    "UI/UX": ["ui/ux", "ux/ui", "figma", "product design"],
    "Game": ["game", "unity", "unreal", "godot"],
    "Mobile": ["mobile", "react native"],
    "Embedded": ["embedded", "firmware", "iot "],
    "SAP/ERP": ["sap", "erp", "odoo", "netsuite"],
    "Salesforce/CRM": ["salesforce", "crm"],
    "System Admin": ["system admin", "sysadmin", "it support", "it helpdesk", "network"],
    "Cloud": ["cloud"],
}

_NON_IT_RE = re.compile(
    r"kế toán|kiểm toán|thu ngân|nhân sự|hành chính|nhân viên văn phòng|lễ tân|"
    r"marketing|content|seo|sale|bán hàng|kinh doanh|telesale|chăm sóc khách hàng|"
    r"tài xế|bảo vệ|phục vụ|giao hàng|công nhân|thợ |xây dựng|cơ khí|điện lạnh|"
    r"dược|y tá|điều dưỡng|giáo viên mầm non|đầu bếp|pha chế|lái xe|thủ kho|"
    r"thiết kế thời trang|trang điểm|spa|bất động sản",
    re.IGNORECASE,
)

_IT_TITLE_RE = re.compile(
    r"\bit\b|cntt|công nghệ thông tin|phần mềm|software|developer|engineer|"
    r"lập trình|programmer|coder|devops|data |dữ liệu|tester|qa|qc|"
    r"technical|solution|architect|cloud|security|system|network|database",
    re.IGNORECASE,
)


def _pad(t: str) -> str:
    return f" {t.lower()} "


def extract_skills(title: str, tags: list[str], category: str = "") -> list[str]:
    """Bóc skill IT chuẩn từ title + tags + category."""
    hay = _pad(" ".join([title or "", category or "", *[t or "" for t in tags]]))
    found: list[str] = []
    for canon, aliases in IT_SKILLS.items():
        for a in aliases:
            if a in hay:
                found.append(canon)
                break
    return found


def is_it_job(title: str, tags: list[str], category: str, source: str) -> bool:
    """itviec = 100% IT. TopCV: loại tin non-IT theo title, còn lại cần có skill IT."""
    if source == "itviec":
        return True
    t = title or ""
    skills = extract_skills(t, tags, category)
    if _NON_IT_RE.search(t) and not skills:
        return False
    if _IT_TITLE_RE.search(t):
        return True
    return bool(skills)
