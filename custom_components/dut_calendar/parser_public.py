"""Logic tải & phân tích trang lichtuan.dut.udn.vn.

Tách riêng khỏi coordinator.py để có thể unit-test độc lập, không phụ
thuộc Home Assistant (chỉ cần beautifulsoup4).
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from .const import LICHTUAN_BASE_URL as BASE_URL


def parse_current_week_info(html: str) -> dict[str, Any] | None:
    """Đọc dropdown 'Tuần'/'Năm học' có sẵn trên trang để biết CHÍNH XÁC
    tuần/năm học hiện tại theo hệ thống của trường — không tự suy luận
    bằng công thức (năm học không bắt đầu cố định 1/9 hay 1/8, ranh
    giới do trường tự set, có năm 52 tuần có năm 53 tuần).

    Trả về None nếu không tìm thấy dropdown (cấu trúc trang đã đổi).
    """
    soup = BeautifulSoup(html, "html.parser")
    week_select = soup.find("select", id="week-container")
    year_select = soup.find("select", id="year-select")
    if week_select is None or year_select is None:
        return None

    selected_week = week_select.find("option", selected=True)
    selected_year = year_select.find("option", selected=True)
    all_week_values = [o.get("value") for o in week_select.find_all("option") if o.get("value")]
    if not selected_week or not selected_year or not all_week_values:
        return None

    return {
        "current_week": selected_week.get("value"),
        "current_year": selected_year.get("value"),
        "min_week_in_year": min(all_week_values),
        "max_week_in_year": max(all_week_values),
    }


def next_year_label(year_label: str) -> str:
    """'2025-2026' -> '2026-2027'."""
    start = int(year_label.split("-")[0])
    return f"{start + 1}-{start + 2}"


def get_week_monday(d: date) -> date:
    """Trả về ngày Thứ Hai của tuần chứa ngày d."""
    return d - timedelta(days=d.weekday())


def build_week_url(monday: date, year_label: str) -> str:
    """Dựng URL lịch tuần cho ngày Thứ Hai + năm học đã xác định trước
    (lấy từ parse_current_week_info, không tự tính công thức)."""
    return f"{BASE_URL}?week={monday.isoformat()}&year={year_label}"


def entry_hash(entry: dict[str, Any]) -> str:
    """Mã băm CHI TIẾT của một mục lịch (ngày+giờ+nội dung+chủ trì).

    Đổi bất kỳ trường nào (kể cả chỉ sửa giờ) là ra mã khác — dùng để
    phát hiện "có thay đổi cần báo" (self._seen_hashes), KHÔNG dùng
    làm khóa lưu trữ lịch sử (xem entry_stable_id bên dưới, tránh hiện
    trùng 2 bản khi trường chỉ sửa nhẹ 1 mục đã có).
    """
    raw = "|".join(
        [
            entry.get("date", ""),
            entry.get("time", ""),
            entry.get("content", ""),
            entry.get("host", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def entry_stable_id(entry: dict[str, Any]) -> str:
    """Khóa định danh ỔN ĐỊNH cho 1 mục lịch (chỉ dựa ngày + nội dung).

    Dùng làm khóa lưu trữ lịch sử — nếu trường sửa giờ/địa điểm/chủ
    trì của MỘT sự kiện đã có (cùng ngày, cùng nội dung), bản ghi cũ
    được GHI ĐÈ bằng bản mới thay vì cộng dồn thành 2 mục hiển thị
    song song trên Calendar.
    """
    raw = "|".join([entry.get("date", ""), entry.get("content", "")])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _clean_text(text: str) -> str:
    # Chuẩn hóa Unicode về dạng dựng sẵn (NFC). Trang nguồn có thể trộn
    # lẫn 2 cách encode dấu tiếng Việt (NFC dựng sẵn / NFD tổ hợp) tùy
    # người nhập liệu — nhìn giống hệt nhau nhưng khác byte, khiến so
    # khớp từ khóa (substring) lặng lẽ thất bại nếu không chuẩn hóa.
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_schedule(html: str, week_label: str = "") -> list[dict[str, Any]]:
    """Phân tích HTML trang lịch tuần, trả về danh sách các mục.

    Trang có thể có NHIỀU bảng (bảng "Lịch Công Tác Tuần" chính, và
    bảng "PHỤ LỤC" riêng nếu có) — đọc TẤT CẢ, không chỉ bảng đầu
    tiên, để không bỏ sót các mục nằm trong Phụ lục.

    Mỗi mục gồm: day (Thứ), date (ngày), time, content, participants,
    location, host, extra, week_label, phu_luc (bool).
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.find_all("table", class_="table")
    if not tables:
        return []

    entries: list[dict[str, Any]] = []

    for table in tables:
        heading = table.find_previous(["h1", "h2", "h3", "h4", "h5"])
        is_phu_luc = bool(heading and "PHỤ LỤC" in heading.get_text(strip=True).upper())

        tbody = table.find("tbody") or table
        current_day = ""
        current_date = ""

        for tr in tbody.find_all("tr", recursive=False):
            tds = tr.find_all("td", recursive=False)
            if not tds:
                continue

            first_classes = tds[0].get("class", []) or []
            if "week" in first_classes:
                combined = _clean_text(tds[0].get_text(separator=" ", strip=True))
                # Trang nguồn không đồng nhất khoảng trắng giữa tên Thứ và
                # ngày (có thứ tách đúng qua "\n", có thứ dính liền thành
                # 1 chuỗi, vd "Thứ tư05/08/2026") -> tách bằng regex theo
                # đúng định dạng ngày dd/mm/yyyy thay vì dựa vào separator.
                date_match = re.search(r"(\d{2}/\d{2}/\d{4})", combined)
                if date_match:
                    current_date = date_match.group(1)
                    current_day = _clean_text(combined[: date_match.start()])
                else:
                    current_day = combined
                    current_date = ""
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
            extra_txt = (
                _clean_text(rest[5].get_text(separator=" ", strip=True)) if len(rest) > 5 else ""
            )

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
                    "phu_luc": is_phu_luc,
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
    raw = unicodedata.normalize("NFC", raw)
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
