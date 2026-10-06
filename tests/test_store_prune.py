"""Prune giữ DB gọn: xoá job cũ/tin đã gỡ, dọn FTS + marks, file nhỏ lại."""
from datetime import datetime, timedelta
from pathlib import Path

from job_crawler import store


def _iso(**delta) -> str:
    return (datetime.now().astimezone() + timedelta(**delta)).isoformat(timespec="seconds")


def _mk(conn, source_id, *, posted_at, last_seen_at):
    store.upsert_job(conn, {
        "source": "itviec", "source_id": source_id, "title": f"Job {source_id}",
        "company": "Example", "url": "https://example.com/j", "is_it": 1,
        "posted_at": posted_at,
        "tags": '["Python"]', "skills": '["Python"]',
        "category": "Data Engineer", "level": "junior",
    })
    # upsert luôn ghi last_seen_at = now → đè thủ công để mô phỏng tuổi thật
    conn.execute(
        "UPDATE jobs SET last_seen_at=? WHERE source=? AND source_id=?",
        (last_seen_at, "itviec", source_id))
    conn.commit()


def test_prune_removes_old_and_stale_keeps_fresh(tmp_path: Path):
    conn = store.connect(tmp_path / "jobs.db")
    _mk(conn, "old-posted", posted_at=_iso(days=-60), last_seen_at=_iso(minutes=-1))
    _mk(conn, "gone-from-source", posted_at=_iso(days=-1), last_seen_at=_iso(days=-10))
    # NULL posted_at → fallback theo first_seen_at (vừa thấy) → chưa xoá
    _mk(conn, "no-posted", posted_at=None, last_seen_at=_iso(minutes=-1))
    _mk(conn, "fresh", posted_at=_iso(days=-2), last_seen_at=_iso(minutes=-1))

    deleted = store.prune(conn, keep_days=30, stale_days=7)

    assert deleted == 2
    ids = {r["source_id"] for r in conn.execute("SELECT source_id FROM jobs")}
    assert ids == {"fresh", "no-posted"}


def test_prune_cleans_fts_and_marks(tmp_path: Path):
    conn = store.connect(tmp_path / "jobs.db")
    _mk(conn, "old", posted_at=_iso(days=-90), last_seen_at=_iso(days=-90))
    _mk(conn, "keep", posted_at=_iso(days=-1), last_seen_at=_iso(minutes=-1))
    conn.execute(
        "INSERT INTO job_marks(source, source_id, viewed, hidden, marked_at)"
        " VALUES ('itviec','old',1,0,?)", (_iso(days=-90),))
    conn.commit()
    n_fts_before = conn.execute("SELECT count(*) FROM jobs_fts").fetchone()[0]

    deleted = store.prune(conn, keep_days=30, stale_days=7)

    assert deleted == 1
    assert n_fts_before == 2
    assert conn.execute("SELECT count(*) FROM jobs_fts").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM job_marks").fetchone()[0] == 0


def test_prune_nothing_to_delete(tmp_path: Path):
    conn = store.connect(tmp_path / "jobs.db")
    _mk(conn, "fresh", posted_at=_iso(days=-1), last_seen_at=_iso(minutes=-1))
    assert store.prune(conn, keep_days=30, stale_days=7) == 0


def test_upsert_stores_relevance(tmp_path: Path):
    conn = store.connect(tmp_path / "jobs.db")
    _mk(conn, "r1", posted_at=_iso(days=-1), last_seen_at=_iso(minutes=-1))
    row = conn.execute(
        "SELECT relevance, matched FROM jobs WHERE source_id='r1'").fetchone()
    # upsert không truyền relevance → NULL; connect() backfill chấm điểm
    assert row["relevance"] is None or row["relevance"] >= 0
    conn.close()
    conn2 = store.connect(tmp_path / "jobs.db")  # backfill chạy ở connect
    row2 = conn2.execute(
        "SELECT relevance, matched FROM jobs WHERE source_id='r1'").fetchone()
    assert row2["relevance"] >= 50  # DE(26) + Python(20) + junior(10)
    assert "Python" in row2["matched"]


def test_upsert_update_keeps_posted_at_iso_and_refreshes_last_seen(tmp_path: Path):
    """Regression: params sai thứ tự từng ghi relevance (số) vào posted_at —
    SQLite đọc '94' là Julian Day cổ đại và prune xoá sạch job còn mới."""
    conn = store.connect(tmp_path / "jobs.db")
    posted = _iso(days=-1)
    _mk(conn, "u1", posted_at=posted, last_seen_at=_iso(hours=-2))

    # lần 2: nội dung mới, posted_at giữ nguyên như nguồn trả về
    store.upsert_job(conn, {
        "source": "itviec", "source_id": "u1", "title": "Job u1 v2",
        "company": "Example", "url": "https://example.com/j", "is_it": 1,
        "posted_at": posted, "posted_text": "1 day ago",
        "tags": '["Python"]', "skills": '["Python"]',
        "category": "Data Engineer", "level": "junior",
        "relevance": 94, "matched": '["Data Engineer","Python"]',
    })
    conn.commit()

    row = conn.execute(
        "SELECT posted_at, last_seen_at, title, relevance, matched FROM jobs"
        " WHERE source_id='u1'").fetchone()
    assert row["posted_at"] == posted              # không bị ghi đè bằng điểm số
    assert row["title"] == "Job u1 v2"             # update thật sự khớp WHERE
    assert row["relevance"] == 94
    assert row["matched"] == '["Data Engineer","Python"]'
    # last_seen được làm mới về "bây giờ" (muộn hơn mốc -2h đã set tay)
    assert row["last_seen_at"] > _iso(hours=-1)
    # và job này không bị prune đột ngột
    assert store.prune(conn, keep_days=30, stale_days=7) == 0
