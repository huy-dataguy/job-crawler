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
