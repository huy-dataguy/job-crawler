"""Parser drift detection — fail loud thay vì ghi dữ liệu rác.

Mỗi nguồn cam kết một tập field thiết yếu. Nếu tỉ lệ job có đủ field tụt dưới
ngưỡng (site đổi schema / đổi render), crawl dừng với `SchemaDrift` để run được
đánh dấu lỗi và không ghi hàng loạt bản ghi thiếu.
"""
from __future__ import annotations

from . import config

ESSENTIALS: dict[str, tuple[str, ...]] = {
    "itviec": ("title", "url"),
    "topcv": ("title", "url"),
    "topdev": ("title", "url", "company"),
}


class SchemaDrift(RuntimeError):
    def __init__(self, source: str, *, fill_rate: float, threshold: float,
                 sample_missing: list[str]):
        self.source = source
        self.fill_rate = fill_rate
        self.threshold = threshold
        self.sample_missing = sample_missing
        super().__init__(
            f"{source}: parser drift — chỉ {fill_rate:.0%} job đủ field thiết yếu "
            f"(ngưỡng {threshold:.0%}); thiếu ở: {', '.join(sample_missing[:5]) or 'n/a'}"
        )


def fill_rate(jobs: list[dict], fields: tuple[str, ...]) -> float:
    if not jobs:
        return 0.0
    ok = sum(1 for j in jobs if all(j.get(f) not in (None, "", "[]") for f in fields))
    return ok / len(jobs)


def ensure(source: str, jobs: list[dict], *, threshold: float | None = None) -> float:
    """Trả fill-rate; raise SchemaDrift nếu dưới ngưỡng."""
    threshold = config.MIN_FILL_RATE if threshold is None else threshold
    fields = ESSENTIALS.get(source, ("title", "url"))
    rate = fill_rate(jobs, fields)
    if jobs and rate < threshold:
        missing = []
        for field in fields:
            if any(j.get(field) in (None, "", "[]") for j in jobs):
                missing.append(field)
        raise SchemaDrift(source, fill_rate=rate, threshold=threshold,
                          sample_missing=missing)
    return rate
