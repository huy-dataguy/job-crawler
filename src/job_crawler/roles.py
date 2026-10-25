"""Role preset — 4 hướng ứng tuyển của Huy (từ 2 CV + JD hợp với mình).

Nguồn chân lý: NguyenQuocHuy_CV_DataEngineer.pdf (chính) +
NguyenQuocHuy_CV_FullStack.pdf (phụ). Data Engineer là hướng chính,
Backend/Fullstack/Data Science là các hướng có thể làm.

Vì sao khớp cả category LẪN title: category do nguồn tự đặt (itviec) hoặc suy
từ skills (topcv/topdev) — ~13% job category rỗng, và tên category không thống
nhất giữa nguồn ("AI Engineer" vs "AI / Machine Learning Engineer"). Role phải
soi title để không bỏ sót job đúng nghề.

Dùng bởi dashboard: đăng ký SQLite function `role_matches(role_csv, title,
category)` — nhận danh sách role phân tách dấu phẩy, trả 1 nếu job thuộc ít
nhất một role.
"""
from __future__ import annotations

import re

# (slug, tên hiển thị, mô tả ngắn, categories chuẩn, pattern title)
# Pattern title chạy trên lowercase, có ranh giới từ (\b) để tránh nhiễu
# ('etl' khớp cả 'settlement' nếu không có \b).
_ROLES: dict[str, tuple[str, str, frozenset[str], str]] = {
    "de": ("Data Engineer", "hướng chính — lakehouse · ETL · pipeline",
           frozenset({"Data Engineer"}),
           r"data engineer|data platform|analytics engineer|big data|"
           r"data warehouse|\bdwh\b|\betl\b|\belt\b|data pipeline"),
    "backend": ("Backend", "API · service · Node.js",
                frozenset({"Backend Developer"}),
                r"backend|back-end|back end"),
    "fullstack": ("Fullstack", "React · Node.js · web app",
                  frozenset({"Fullstack Developer"}),
                  r"fullstack|full-stack|full stack"),
    "ds": ("Data Science", "ML · AI · model",
           frozenset({"AI Engineer", "AI / Machine Learning Engineer",
                      "Data Scientist"}),
           r"data scien|machine learning|\bai engineer\b|\bml engineer\b|"
           r"generative ai|deep learning"),
}


def names() -> dict[str, str]:
    """slug → tên hiển thị, giữ thứ tự khai báo."""
    return {slug: spec[0] for slug, spec in _ROLES.items()}


def split(role_csv: str) -> list[str]:
    return [r.strip() for r in (role_csv or "").split(",") if r.strip() in _ROLES]


def matches(role_csv: str, title: str | None, category: str | None) -> int:
    """1 nếu job thuộc ít nhất một role trong danh sách — SQLite function."""
    title_l = (title or "").lower()
    category = (category or "").strip()
    for slug in split(role_csv):
        _name, _desc, cats, pat = _ROLES[slug]
        if category in cats or re.search(pat, title_l):
            return 1
    return 0
