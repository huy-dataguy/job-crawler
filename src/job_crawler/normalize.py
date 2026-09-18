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


# --- Canonical đồng nhất xuyên nguồn --------------------------------------
# Mọi job (itviec/topcv) đều có: category, level, salary_min/max, exp_min.

# skill chuẩn → category chuẩn (đặt tên theo style category của itviec)
SKILL_CATEGORY: dict[str, str] = {
    "Java": "Backend Developer", "Python": "Backend Developer",
    "Golang": "Backend Developer", "Node.js": "Backend Developer",
    "PHP": "Backend Developer", ".NET": "Backend Developer",
    "C++": "Backend Developer", "Kotlin": "Backend Developer",
    "Backend": "Backend Developer", "API/Microservices": "Backend Developer",
    "Spring": "Backend Developer", "Django": "Backend Developer",
    "Laravel": "Backend Developer",
    "JavaScript": "Frontend Developer", "TypeScript": "Frontend Developer",
    "React": "Frontend Developer", "Angular": "Frontend Developer",
    "Vue": "Frontend Developer", "Frontend": "Frontend Developer",
    "Android": "Mobile Developer", "iOS": "Mobile Developer",
    "Dart/Flutter": "Mobile Developer", "Mobile": "Mobile Developer",
    "Fullstack": "Fullstack Developer",
    "DevOps": "DevOps Engineer", "Docker": "DevOps Engineer",
    "Kubernetes": "DevOps Engineer", "CI/CD": "DevOps Engineer",
    "Terraform": "DevOps Engineer", "Cloud": "DevOps Engineer",
    "AWS": "DevOps Engineer", "Azure": "DevOps Engineer",
    "GCP": "DevOps Engineer",
    "Data Engineer": "Data Engineer", "Data Analyst": "Data Analyst",
    "Data Scientist": "Data Scientist", "AI/ML": "AI Engineer",
    "SQL": "Data Engineer",
    "Tester/QA": "Tester/QC", "Security": "Security Engineer",
    "System Admin": "System/Network Admin",
    "Game": "Game Developer", "Embedded": "Embedded Engineer",
    "BA": "Business Analyst", "Product Owner": "Product Owner",
    "Project Manager": "Project Manager", "Scrum": "Project Manager",
    "UI/UX": "UI/UX Designer", "SAP/ERP": "ERP Consultant",
    "Salesforce/CRM": "CRM Consultant",
    "WordPress": "Backend Developer", "IT General": "IT General",
}

# level → exp_min ước tính (dùng cho nguồn không ghi số năm, vd itviec)
LEVEL_EXP: dict[str, float] = {
    "intern": 0.0, "fresher": 0.0, "junior": 1.0, "middle": 2.0,
    "senior": 3.0, "lead": 4.0, "manager": 5.0,
}

_LEVEL_RES: list[tuple[str, str]] = [
    ("intern", r"intern|thực tập|tts\b"),
    ("fresher", r"fresher|mới tốt nghiệp|junior fresher|graduate"),
    ("junior", r"junior|\bjr\.?\b"),
    ("middle", r"middle|\bmid\.?\b"),
    ("senior", r"senior|\bsr\.?\b"),
    ("lead", r"\blead\b|team lead|tech lead|trưởng nhóm"),
    ("manager", r"manager|head\b|director|giám đốc|trưởng phòng|quản lý"),
]


def parse_level(title: str) -> str:
    """Bóc seniority từ title — chạy cho cả 2 nguồn."""
    t = (title or "").lower()
    for level, pat in _LEVEL_RES:
        if re.search(pat, t):
            return level
    return ""


def infer_category(title: str, skills: list[str], category: str) -> str:
    """Giữ category có sẵn (itviec); topcv suy từ skills → title."""
    if category:
        return category
    for s in skills:
        if s in SKILL_CATEGORY:
            return SKILL_CATEGORY[s]
    t = (title or "").lower()
    for pat, cat in [(r"tester|qa|qc|kiểm thử", "Tester/QC"),
                     (r"data|dữ liệu", "Data Engineer"),
                     (r"devops|cloud|infra", "DevOps Engineer"),
                     (r"backend|server", "Backend Developer"),
                     (r"frontend|web\b", "Frontend Developer"),
                     (r"mobile|android|ios", "Mobile Developer"),
                     (r"security|bảo mật", "Security Engineer"),
                     (r"designer|thiết kế", "UI/UX Designer")]:
        if re.search(pat, t):
            return cat
    return ""


_USD = 0.026  # 1 USD ≈ 0.026 triệu VND


def parse_salary_range(text: str) -> tuple[float | None, float | None]:
    """'12 - 15 triệu' → (12,15); '$1,000 - $2,000' → đổi sang triệu VND; 'N/A' → (None,None)."""
    t = (text or "").lower().replace(",", "")
    if not t or "thỏa thuận" in t or t.strip() in ("n/a", "-", "negotiable"):
        return (None, None)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*(triệu|tr\b|million)", t)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    m = re.search(r"\$(\d+(?:\.\d+)?)\s*[-–]\s*\$(\d+(?:\.\d+)?)", t)
    if m:
        return (round(float(m.group(1)) * _USD, 1), round(float(m.group(2)) * _USD, 1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(triệu|tr\b)", t)
    if m:
        v = float(m.group(1))
        return (v, v)
    m = re.search(r"\$(\d+(?:\.\d+)?)", t)
    if m:
        v = round(float(m.group(1)) * _USD, 1)
        return (v, v)
    m = re.search(r"(\d+)\s*k\b", t)
    if m:
        v = float(m.group(1)) / 1000
        return (v, v)
    return (None, None)


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
    "System Admin": ["system admin", "sysadmin", "it support", "it helpdesk", "network",
                     "support engineer"],
    "Cloud": ["cloud"],
    "WordPress": ["wordpress"],
    # Alias chung chung (developer, triển khai…) KHÔNG cho vào đây vì dễ lật
    # job sale/marketing thành IT — chỉ alias nào chắc chắn mới thêm.
    "IT General": ["cntt", "công nghệ thông tin", "software engineer", "head of engineering",
                   "nhân viên lập trình", "điều phối viên it"],
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

# Role kỹ thuật explicit — đủ mạnh để giữ lại job dù title dính từ non-IT
# (vd "Presales Engineer", "Cloud Solution Architect" dính chữ "sale"/tư vấn)
_STRONG_IT_ROLE_RE = re.compile(
    r"developer|software engineer|presales|s presales|solution architect|"
    r"support engineer|it support|it helpdesk|head of engineering|"
    r"nhân viên it|nhân viên lập trình|cntt|"
    r"tester|devops|data engineer|data analyst|system admin|network admin",
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
    """itviec = 100% IT. TopCV:
    - title dính non-IT (sale/kế toán/marketing/CNC/hành chính…) → chỉ giữ
      nếu là role kỹ thuật explicit (dev/tester/support/presales/architect/…).
      Sale phần mềm, telesale, CNC, marketing-AI đều loại.
    - còn lại: có marker IT hoặc bóc được skill → IT."""
    if source == "itviec":
        return True
    t = title or ""
    if _NON_IT_RE.search(t):
        return bool(_STRONG_IT_ROLE_RE.search(t))
    skills = extract_skills(t, tags, category)
    if _IT_TITLE_RE.search(t):
        return True
    return bool(skills)
