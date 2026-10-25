"""Lớp auth của API production (api/index.py): mọi request phải mang Bearer
token hợp lệ của đúng ALLOWED_EMAIL, verify qua Supabase Auth. Test không đụng
mạng thật — urlopen được thay bằng stub."""
import importlib
import json
import sys
import urllib.error
from pathlib import Path

import pytest
from fastapi import HTTPException

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

api = importlib.import_module("api.index")


class _FakeResp:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "pk-test")
    monkeypatch.setenv("ALLOWED_EMAIL", "owner@gmail.com")
    monkeypatch.delenv("AUTH_DISABLED", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    api._TOKEN_CACHE.clear()
    yield
    api._TOKEN_CACHE.clear()


def _stub_urlopen(monkeypatch, email="owner@gmail.com"):
    state = {"n": 0}

    def fake(req, timeout=None):
        state["n"] += 1
        return _FakeResp({"email": email})

    monkeypatch.setattr(api.urllib.request, "urlopen", fake)
    return state


def test_thieu_header_la_401():
    with pytest.raises(HTTPException) as e:
        api.require_user(authorization="")
    assert e.value.status_code == 401


def test_sai_scheme_la_401():
    with pytest.raises(HTTPException) as e:
        api.require_user(authorization="Basic abcdef")
    assert e.value.status_code == 401


def test_token_dung_email_dung_tra_ve_email_va_an_cache(monkeypatch):
    calls = _stub_urlopen(monkeypatch)
    assert api.require_user(authorization="Bearer tok1") == "owner@gmail.com"
    assert api.require_user(authorization="Bearer tok1") == "owner@gmail.com"
    assert calls["n"] == 1  # lần 2 ăn cache, không gọi Supabase lần nữa


def test_email_so_va_hoa_khong_phan_biet(monkeypatch):
    _stub_urlopen(monkeypatch, email="Owner@Gmail.com")
    assert api.require_user(authorization="Bearer tok-case") == "owner@gmail.com"


def test_token_hop_le_nhung_sai_email_la_401(monkeypatch):
    _stub_urlopen(monkeypatch, email="ai.khac@gmail.com")
    with pytest.raises(HTTPException) as e:
        api.require_user(authorization="Bearer tok2")
    assert e.value.status_code == 401
    assert "không có quyền" in e.value.detail
    assert "tok2" not in api._TOKEN_CACHE  # email sai không được cache


def test_supabase_tu_choi_hoac_khong_tra_loi_thi_401(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    monkeypatch.setattr(api.urllib.request, "urlopen", boom)
    with pytest.raises(HTTPException) as e:
        api.require_user(authorization="Bearer tok3")
    assert e.value.status_code == 401  # fail-closed


def test_auth_disabled_chi_hieu_ngoai_vercel(monkeypatch):
    calls = _stub_urlopen(monkeypatch)
    monkeypatch.setenv("AUTH_DISABLED", "1")
    assert api.require_user(authorization="") == "local"  # dev máy cá nhân
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(HTTPException):
        api.require_user(authorization="")  # trên Vercel: luôn khóa
    assert calls["n"] == 0


def test_cache_het_han_thi_verify_lai(monkeypatch):
    calls = _stub_urlopen(monkeypatch)
    api.require_user(authorization="Bearer tok4")
    api._TOKEN_CACHE["tok4"] = (0.0, "owner@gmail.com")  # ép hết hạn
    api.require_user(authorization="Bearer tok4")
    assert calls["n"] == 2


def test_thieu_cau_hinh_thi_503_khong_lo(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    with pytest.raises(HTTPException) as e:
        api.require_user(authorization="Bearer tok5")
    assert e.value.status_code == 503


def test_sync_tu_choi_chay_khi_thieu_allowed_email(monkeypatch):
    # RLS là lớp bảo vệ dữ liệu trên cloud — sync phải fail to receive khi
    # không biết email chủ, đừng để chạy mà quên khóa.
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://x")
    monkeypatch.delenv("ALLOWED_EMAIL", raising=False)
    sys.path.insert(0, str(REPO / "scripts"))
    sync = importlib.import_module("sync_supabase")
    with pytest.raises(SystemExit):
        sync.main()
