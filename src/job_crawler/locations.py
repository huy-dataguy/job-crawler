"""Match source location labels without relying on accents or English spelling.

Keep historical source place names separate: do not infer administrative mergers.
"""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata


def folded(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.findall(r"[a-z0-9]+", text))


_NAMES = (
    "An Giang", "Bà Rịa - Vũng Tàu", "Bắc Giang", "Bắc Kạn", "Bạc Liêu", "Bắc Ninh",
    "Bến Tre", "Bình Định", "Bình Dương", "Bình Phước", "Bình Thuận", "Cà Mau",
    "Cần Thơ", "Cao Bằng", "Đà Nẵng", "Đắk Lắk", "Đắk Nông", "Điện Biên",
    "Đồng Nai", "Đồng Tháp", "Gia Lai", "Hà Giang", "Hà Nam", "Hà Nội", "Hà Tĩnh",
    "Hải Dương", "Hải Phòng", "Hậu Giang", "Hòa Bình", "Hồ Chí Minh", "Hưng Yên",
    "Khánh Hòa", "Kiên Giang", "Kon Tum", "Lai Châu", "Lâm Đồng", "Lạng Sơn",
    "Lào Cai", "Long An", "Nam Định", "Nghệ An", "Ninh Bình", "Ninh Thuận",
    "Phú Thọ", "Phú Yên", "Quảng Bình", "Quảng Nam", "Quảng Ngãi", "Quảng Ninh",
    "Quảng Trị", "Sóc Trăng", "Sơn La", "Tây Ninh", "Thái Bình", "Thái Nguyên",
    "Thanh Hóa", "Huế", "Tiền Giang", "Trà Vinh", "Tuyên Quang", "Vĩnh Long",
    "Vĩnh Phúc", "Yên Bái",
)
_EXTRA = {
    "Hồ Chí Minh": ("HCM", "HCMC", "TPHCM", "TP HCM", "Saigon", "Sai Gon"),
    "Hà Nội": ("HN", "Hanoi"),
    "Đà Nẵng": ("Danang",),
    "Hải Phòng": ("Haiphong",),
    "Bà Rịa - Vũng Tàu": ("Ba Ria", "Vung Tau", "BRVT"),
    "Huế": ("Thừa Thiên Huế",),
    "Đắk Lắk": ("Daklak", "Đắc Lắc"),
}
_ALIASES = {name: tuple(dict.fromkeys(folded(v) for v in (name, *_EXTRA.get(name, ()))))
            for name in _NAMES}
_PATTERNS = {name: re.compile(r"(?<!\w)(?:" + "|".join(re.escape(a) for a in aliases) + r")(?!\w)")
             for name, aliases in _ALIASES.items()}
UNKNOWN = "__unknown__"


@lru_cache(maxsize=8192)
def provinces(text: str | None, address: bool = False) -> frozenset[str]:
    result = set()
    for line in (text or "").splitlines():
        normalized = folded(line)
        found = [(match.end(), name) for name, pattern in _PATTERNS.items()
                 for match in pattern.finditer(normalized)]
        if address and found:
            # Street names can contain another province: use the final locality
            # in each source address line, and retain multiple office lines.
            result.add(max(found)[1])
        else:
            result.update(name for _, name in found)
    return frozenset(result)


@lru_cache(maxsize=16384)
def matches(text: str | None, selected: str, address: int = 0) -> int:
    found = provinces(text, bool(address))
    if selected == UNKNOWN:
        return int(not found)
    normalized = folded(selected)
    canonical = next((name for name, aliases in _ALIASES.items() if normalized in aliases), None)
    if canonical:
        return int(canonical in found)
    # Preserve compatibility with existing free-text city API requests.
    return int(bool(normalized) and f" {normalized} " in f" {folded(text or '')} ")


def options(observed: set[str]) -> list[dict[str, str]]:
    priority = {"Hồ Chí Minh": 0, "Hà Nội": 1, "Đà Nẵng": 2}
    return [{"value": name, "label": "TP. Hồ Chí Minh" if name == "Hồ Chí Minh" else name}
            for name in sorted(observed, key=lambda n: (priority.get(n, 3), folded(n)))]
