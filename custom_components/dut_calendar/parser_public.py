"""Logic tải & phân tích trang lichtuan.dut.udn.vn.

Tách riêng khỏi coordinator.py để có thể unit-test độc lập, không phụ
thuộc Home Assistant (chỉ cần beautifulsoup4).
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from .const import LICHTUAN_BASE_URL as BASE_URL


def get_academic_year(d: date) -> str:
    """Trả về năm học dạng '2025-2026'.

    Quy ước: năm học bắt đầu từ tháng 9. Vậy tháng 1-8 thuộc năm học
    (year-1)-(year), tháng 9-12 thuộc năm học (year)-(year+1).
    """
    if d.month >= 9:
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def get_week_monday(d: date) -> date:
    """Trả về ngày Thứ Hai của tuần chứa ngày d."""
    return d - timedelta(days=d.weekday())


def build_week_url(monday: date) -> str:
    """Dựng URL lịch tuần cho ngày Thứ Hai đã cho."""
    year_str = get_academic_year(monday)
    return f"{BASE_URL}?week={monday.isoformat()}&year={year_str}"


def entry_hash(entry: dict[str, Any]) -> str:
    """Tạo mã băm ổn định cho một mục lịch, dùng để chống báo trùng."""
    raw = "|".join(
        [
            entry.get("date", ""),
            entry.get("time", ""),
            entry.get("content", ""),
            entry.get("host", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_schedule(html: str, week_label: str = "") -> list[dict[str, Any]]:
    """Phân tích HTML trang lịch tuần, trả về danh sách các mục.

    Mỗi mục gồm: day (Thứ), date (ngày), time, content, participants,
    location, host, extra, week_label.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table")
    if table is None:
        return []
    tbody = table.find("tbody")
    if tbody is None:
        return []

    entries: list[dict[str, Any]] = []
    current_day = ""
    current_date = ""

    for tr in tbody.find_all("tr", recursive=False):
        tds = tr.find_all("td", recursive=False)
        if not tds:
            continue

        first_classes = tds[0].get("class", []) or []
        if "week" in first_classes:
            raw_parts = tds[0].get_text(separator="\n", strip=True).split("\n")
            parts = [_clean_text(p) for p in raw_parts if _clean_text(p)]
            current_day = parts[0] if parts else ""
            current_date = parts[1] if len(parts) > 1 else ""
            rest = tds[1:]
        else:
            rest = tds

        if len(rest) < 5:
            # Dòng không đủ cột dữ liệu (thời gian/nội dung/thành phần/địa điểm/chủ trì)
            continue

        time_txt = _clean_text(rest[0].get_text(separator=" ", strip=True))
        content_txt = _clean_text(rest[1].get_text(separator=" ", strip=True))
        participants_txt = _clean_text(rest[2].get_text(separator=" ", strip=True))
        location_txt = _clean_text(rest[3].get_text(separator=" ", strip=True))
        host_txt = _clean_text(rest[4].get_text(separator=" ", strip=True))
        extra_txt = _clean_text(rest[5].get_text(separator=" ", strip=True)) if len(rest) > 5 else ""

        if not any([time_txt, content_txt, participants_txt, location_txt, host_txt]):
            continue

        entries.append(
            {
                "day": current_day,
                "date": current_date,
                "time": time_txt,
                "content": content_txt,
                "participants": participants_txt,
                "location": location_txt,
                "host": host_txt,
                "extra": extra_txt,
                "week_label": week_label,
            }
        )

    return entries


def parse_event_datetime(
    date_str: str, time_str: str
) -> tuple[Any, Any, bool]:
    """Chuyển cột 'date' (dd/mm/yyyy) + 'time' của 1 mục lịch thành (start, end, all_day).

    - Nếu 'time' chứa 2 mốc giờ (vd '08:00 - 10:00') -> sự kiện có giờ,
      start/end là datetime (naive, chưa gắn timezone).
    - Nếu chỉ có 1 mốc giờ (vd '07:00') -> mặc định kéo dài 1 tiếng.
    - Nếu không tìm thấy giờ nào (ô trống, hoặc chữ như 'Cả ngày') ->
      coi là sự kiện cả ngày, start/end là `date` (all_day=True).
    - Nếu không parse được ngày -> trả về (None, None, True).
    """
    try:
        day_s, month_s, year_s = date_str.strip().split("/")
        ev_date = date(int(year_s), int(month_s), int(day_s))
    except (ValueError, AttributeError):
        return None, None, True

    times = re.findall(r"(\d{1,2}):(\d{2})", time_str or "")

    if not times:
        return ev_date, ev_date + timedelta(days=1), True

    def _mk(hm: tuple[str, str]) -> datetime:
        h, m = int(hm[0]), int(hm[1])
        h = min(h, 23)
        m = min(m, 59)
        return datetime(ev_date.year, ev_date.month, ev_date.day, h, m)

    start = _mk(times[0])
    if len(times) >= 2:
        end = _mk(times[1])
        if end <= start:
            end = start + timedelta(hours=1)
    else:
        end = start + timedelta(hours=1)

    return start, end, False


def parse_keyword_groups(raw: str) -> list[dict[str, Any]]:
    """Phân tích cấu hình từ khóa nhiều dòng thành danh sách nhóm.

    Mỗi DÒNG là một nhóm (1 sensor). Cú pháp mỗi dòng:

        Nhãn hiển thị: biến thể 1, biến thể 2, biến thể 3

    Nếu dòng không có dấu ':', cả dòng được coi là nhãn kiêm biến thể
    duy nhất (tương thích ngược với cấu hình 1-từ-khóa-1-dòng).

    Ví dụ:
        Lê Minh Tiến: Lê Minh Tiến, LMT, Tiến LM, Thầy Tiến
        Khoa Cơ khí Giao thông: Khoa Cơ khí Giao thông, CKGT
        Bộ môn Kỹ thuật Ô tô: Kỹ thuật Ô tô, KTOT

    Trả về: [{"label": "Lê Minh Tiến", "variants": ["Lê Minh Tiến", "LMT", ...]}, ...]
    """
    groups: list[dict[str, Any]] = []
    for raw_line in raw.replace(";", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if ":" in line:
            label, variants_str = line.split(":", 1)
            label = label.strip()
            variants = [v.strip() for v in variants_str.split(",") if v.strip()]
            if not variants:
                variants = [label]
        else:
            label = line
            variants = [line]

        if not label:
            continue

        groups.append({"label": label, "variants": variants})

    return groups


_ACRONYM_RE = re.compile(r"^[A-ZÀ-Ỹ0-9]{2,8}$")


def _variant_matches(variant: str, haystack_original: str, haystack_lower: str) -> bool:
    """Kiểm tra 1 biến thể có khớp trong nội dung không.

    - Biến thể dạng viết tắt toàn chữ HOA ngắn (vd 'CKGT', 'LMT'):
      so khớp CÓ phân biệt hoa/thường + ranh giới từ (word boundary),
      để tránh khớp nhầm vào giữa một từ khác.
    - Biến thể thông thường (tên đầy đủ, cụm từ dài...): so khớp
      không phân biệt hoa/thường theo kiểu "chuỗi con" (substring),
      như trước đây.
    """
    variant = variant.strip()
    if not variant:
        return False

    if _ACRONYM_RE.match(variant):
        pattern = r"(?<!\w)" + re.escape(variant) + r"(?!\w)"
        return re.search(pattern, haystack_original) is not None

    return variant.lower() in haystack_lower


def filter_by_keywords(
    entries: list[dict[str, Any]], keyword_groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Lọc các mục có chứa (không phân biệt hoa/thường) ít nhất 1 nhóm từ khóa.

    Tìm trong các trường: content, participants, host, location.
    Trả về bản sao mỗi mục kèm:
    - 'matched_keywords': danh sách NHÃN nhóm đã khớp (dùng để map ra sensor)
    - 'matched_variants': danh sách biến thể cụ thể đã khớp (để hiển thị debug)
    """
    if not keyword_groups:
        return []

    results: list[dict[str, Any]] = []

    for entry in entries:
        haystack_original = " ".join(
            [
                entry.get("content", ""),
                entry.get("participants", ""),
                entry.get("host", ""),
                entry.get("location", ""),
            ]
        )
        haystack_lower = haystack_original.lower()

        matched_labels: list[str] = []
        matched_variants: list[str] = []

        for group in keyword_groups:
            hit_variants = [
                v
                for v in group["variants"]
                if _variant_matches(v, haystack_original, haystack_lower)
            ]
            if hit_variants:
                matched_labels.append(group["label"])
                matched_variants.extend(hit_variants)

        if matched_labels:
            new_entry = dict(entry)
            new_entry["matched_keywords"] = matched_labels
            new_entry["matched_variants"] = matched_variants
            new_entry["id"] = entry_hash(entry)
            results.append(new_entry)

    return results
