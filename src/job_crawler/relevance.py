"""Chấm điểm độ liên quan của job với profile của Huy (2 CV chấm từ PDF).

Nguồn chân lý: NguyenQuocHuy_CV_DataEngineer.pdf + NguyenQuocHuy_CV_FullStack.pdf
(một người, 2 hướng ứng tuyển — DE là hướng chính, FullStack là hướng phụ).

Profile chưng cất từ CV:
- Hướng chính  — Data Engineer: Python, SQL, Spark, Kafka, Airflow, Flink,
  ClickHouse, PostgreSQL, MinIO/S3, Iceberg, ELT/ETL, data pipeline, lakehouse,
  Docker, Windmill, GCP/AWS.
- Hướng phụ    — FullStack: React, TypeScript, JavaScript, Node.js, FastAPI,
  Tailwind, Redux, Next.js, GraphQL, WebSocket.
- Trọng tâm chung: Python, SQL, Docker, PostgreSQL, FastAPI, cloud.
- Bối cảnh: tốt nghiệp 9/2026, ~6 tháng DE ở Pythera → fit nhất
  fresher/junior/middle.

Điểm 0–100, thuần Python không phụ thuộc nguồn. Output kèm list `matched`
(các term khớp, nặng nhất trước) để hiện badge/tooltip và tin Telegram.
"""
from __future__ import annotations

import json
import re

# --- Bảng term profile: (tên hiển thị, trọng số, alias lowercase) ------------
# Trọng số thể hiện mức "là nghề của mình": term DE/dataPlatform = 10–12,
# term fullstack cốt lõi = 6–8, term lân cận = 3–5, term xa = 1–2.
_TERMS: list[tuple[str, int, tuple[str, ...]]] = [
    # Hướng chính: Data / Platform
    ("Data Engineer", 12, ("data engineer", "data platform engineer", "analytics engineer",
                           "data developer")),
    ("ETL/ELT", 11, ("etl", "elt", "data pipeline", "data modeling", "data modelling",
                     "lakehouse", "data warehouse", "big data", "dwh")),
    ("Airflow", 10, ("airflow",)),
    ("Kafka", 10, ("kafka",)),
    ("Spark", 10, ("spark", "pyspark")),
    ("Flink", 9, ("flink",)),
    ("ClickHouse", 9, ("clickhouse",)),
    ("Iceberg", 8, ("iceberg", "paimon", "hudi", "delta lake")),
    ("MinIO/S3", 7, ("minio", "s3", "object storage")),
    ("Trino", 7, ("trino", "presto", "hive", "superset", "databricks")),
    ("dbt", 8, ("dbt",)),
    ("Windmill", 7, ("windmill", "dagster", "prefect")),
    # Hướng phụ: FullStack
    ("React", 8, ("react", "reactjs", "next.js", "nextjs")),
    ("Node.js", 7, ("node.js", "nodejs", "node js")),
    ("TypeScript", 7, ("typescript",)),
    ("FastAPI", 8, ("fastapi", "flask")),
    ("Tailwind", 5, ("tailwind", "vite", "redux", "webpack")),
    ("GraphQL", 5, ("graphql",)),
    ("WebSocket", 5, ("websocket", "real-time", "realtime")),
    # Trọng tâm chung
    ("Python", 10, ("python",)),
    ("SQL", 9, ("sql", "mysql", "postgresql", "postgres", "oracle db", "mongodb",
                "database", "query optimization")),
    ("Docker", 7, ("docker",)),
    ("Kubernetes", 5, ("kubernetes", "k8s", "helm")),
    ("GCP", 6, ("gcp", "google cloud", "bigquery", "dataproc")),
    ("AWS", 6, ("aws", "amazon web services", "sagemaker", "redshift", "glue")),
    ("Redis", 5, ("redis", "elasticsearch", "opensearch")),
    # Lân cận có trong CV (LLM/RAG ở cả 2 CV)
    ("LLM/RAG", 6, ("llm", "rag", "langgraph", "langchain", "gen ai", "generative ai",
                    "ai engineer", "machine learning", "deep learning")),
    # Term cần nhận diện nhưng trọng số thấp (không phải hướng ứng tuyển chính)
    ("JavaScript", 6, ("javascript",)),
    ("Vue", 4, ("vue", "vuejs", "nuxt", "angular")),
    ("CI/CD", 4, ("ci/cd", "cicd", "jenkins", "gitlab ci", "github actions", "devops")),
    ("Linux", 3, ("linux", "shell", "bash")),
    ("Java", 2, ("java", "spring",)),
    ("Golang", 2, ("golang",)),
    ("PHP", 1, ("php", "laravel", "wordpress",)),
    (".NET", 1, (".net", "c#", "dotnet",)),
    ("Mobile", 1, ("android", "ios", "flutter", "react native", "mobile")),
    ("Game", 1, ("unity", "unreal", "game dev",)),
    ("Embedded", 1, ("embedded", "firmware", "iot")),
]

# Điểm nền theo category chuẩn (cột `category` sau normalize).
_CATEGORY_SCORE: dict[str, int] = {
    "Data Engineer": 26,
    "Fullstack Developer": 20,
    "Backend Developer": 14,
    "AI Engineer": 13,
    "Data Analyst": 10,
    "DevOps Engineer": 10,
    "Frontend Developer": 9,
    "Data Scientist": 8,
    "System/Network Admin": 3,
    "Tester/QC": 3,
    "Security Engineer": 3,
    "Business Analyst": 2,
    "Product Owner": 2,
    "Project Manager": 2,
    "UI/UX Designer": 2,
    "Game Developer": 2,
    "Mobile Developer": 2,
    "Embedded Engineer": 2,
    "ERP Consultant": 2,
    "CRM Consultant": 2,
    "IT General": 4,
}

# Điều chỉnh theo level (tốt nghiệp 2026 + ~6 tháng kinh nghiệm).
_LEVEL_ADJ: dict[str, int] = {
    "intern": 4, "fresher": 10, "junior": 10, "middle": 6,
    "senior": 0, "lead": -10, "manager": -15, "": 4,
}

def _as_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except (TypeError, ValueError):
            v = [v]
    return [str(x) for x in v if x]


def score_job(job: dict) -> tuple[int, list[str]]:
    """Trả về (score 0-100, matched terms). Không mutate job."""
    title = (job.get("title") or "").lower()
    skills = " ".join(_as_list(job.get("skills"))).lower()
    tags = " ".join(_as_list(job.get("tags"))).lower()
    category = (job.get("category") or "").lower()

    # Mỗi field một mức nhân: title nói lên nghề nhất (x3), skill chuẩn (x2),
    # tag thô x1. Một term chỉ được tính ở field nặng nhất nó xuất hiện.
    def _norm(s: str) -> str:
        # Chuẩn hoá dấu câu ranh giới thành space; giữ . / # + - cho alias ghép
        # (".net", "ci/cd", "node.js", "c#").
        s = re.sub(r"[,;:()\[\]|&_\"'“”]+", " ", s.lower())
        s = re.sub(r"\s+", " ", s).strip()
        return f" {s} "

    hays: list[tuple[str, int]] = [(_norm(title), 3), (_norm(skills), 2), (_norm(tags), 1)]
    matched: list[tuple[str, int]] = []
    cat_key = (job.get("category") or "").strip()
    total = _CATEGORY_SCORE.get(cat_key, 0)
    if cat_key not in _CATEGORY_SCORE and re.search(r"\bdata\b|\bdữ liệu\b", category):
        # category lạ (vd itviec đổi tên nhóm) — tiếng nói data thì có điểm nền
        total += 12

    for name, weight, aliases in _TERMS:
        best = 0
        for hay, mult in hays:
            for a in aliases:
                if f" {a} " in hay:
                    best = max(best, weight * mult)
                    break
            if best == weight * 3:  # đã match ở title — field nặng nhất
                break
        if best:
            total += best
            matched.append((name, best))

    # Level fit: ưu tiên level bóc từ title; thiếu thì suy từ exp_min.
    # Level không rõ chỉ được cộng khi job có tín hiệu khớp (tránh job ngoài
    # profile vẫn mang điểm dương).
    level = (job.get("level") or "").strip().lower()
    if level in _LEVEL_ADJ and (level or matched):
        total += _LEVEL_ADJ[level]
    elif job.get("exp_min") is not None and matched:
        try:
            e = float(job["exp_min"])
            total += 6 if e <= 2 else (3 if e <= 3 else (-6 if e >= 5 else 0))
        except (TypeError, ValueError):
            pass

    matched.sort(key=lambda kv: -kv[1])
    return max(0, min(100, round(total))), [name for name, _ in matched[:8]]


def annotate(job: dict) -> dict:
    """Gán `relevance` + `matched` (JSON) vào job dict — dùng trước khi upsert."""
    score, matched = score_job(job)
    job["relevance"] = score
    job["matched"] = json.dumps(matched, ensure_ascii=False)
    return job


def backfill_row(title: str, category: str, tags: str, skills: str,
                 level: str, exp_min) -> tuple[int, str]:
    """Wrapper cho backfill DB cũ: nhận raw columns, trả (score, matched JSON)."""
    score, matched = score_job({
        "title": title, "category": category, "tags": tags, "skills": skills,
        "level": level, "exp_min": exp_min,
    })
    return score, json.dumps(matched, ensure_ascii=False)
