"""Logic phân tích HTML của cổng cb.dut.udn.vn (thuần Python, dễ test độc lập)."""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup


def parse_hidden_field(html: str, field_id: str) -> str | None:
    """Lấy value của 1 input ẩn ASP.NET WebForms (vd __VIEWSTATE)."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("input", id=field_id)
    return tag.get("value", "") if tag else None


def is_login_page(html: str) -> bool:
    """Kiểm tra HTML trả về có phải trang đăng nhập không (session hết hạn)."""
    return "Login_txtUS" in html or "Login_txtPW" in html


def parse_exam_duty(html: str, hoc_ky_label: str = "") -> list[dict[str, Any]]:
    """Phân tích bảng lịch coi thi (API PhongThiDK) thành danh sách ca thi.

    Cấu trúc cột thật của bảng #ctrPhongThiDK_Grid:
    STT | Mã ca thi | Tên ca thi | Thời gian làm bài thi | Phòng | Xuất |
    Đề mở | Cán bộ 1 | Đăng ký | Cán bộ 2 | Đăng ký | Copy email sinh viên
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="ctrPhongThiDK_Grid")
    if table is None:
        return []

    results: list[dict[str, Any]] = []
    for tr in table.find_all("tr", class_="GridRow"):
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue

        texts = [td.get_text(strip=True) for td in tds]
        ma_ca_thi = texts[1]
        ten_mon = texts[2]
        thoi_gian = texts[3]
        phong = texts[4]
        xuat = texts[5]
        can_bo_1 = texts[7]
        can_bo_2 = texts[9]

        if not any([ma_ca_thi, ten_mon, thoi_gian]):
            continue

        results.append(
            {
                "ma_ca_thi": ma_ca_thi,
                "mon_thi": ten_mon,
                "thoi_gian_raw": thoi_gian,
                "phong": phong,
                "xuat": xuat,
                "can_bo_1": can_bo_1,
                "can_bo_2": can_bo_2,
                "hoc_ky_label": hoc_ky_label,
            }
        )

    return results


_TIME_RE = re.compile(r"(\d{1,2})h(\d{2})-(\d{2})/(\d{2})/(\d{4})")


def parse_exam_datetime(
    thoi_gian_raw: str, duration_minutes: int
) -> tuple[datetime | None, datetime | None]:
    """Chuyển 'Thời gian làm bài thi' dạng '7h00-20/05/2026' -> (start, end).

    Không có giờ kết thúc trong dữ liệu nguồn, nên end = start + duration_minutes
    (mặc định cấu hình được, vd 90 phút).
    """
    m = _TIME_RE.match(thoi_gian_raw.strip())
    if not m:
        return None, None

    h, mnt, dd, mm, yyyy = (int(x) for x in m.groups())
    try:
        start = datetime(yyyy, mm, dd, h, mnt)
    except ValueError:
        return None, None

    end = start + timedelta(minutes=duration_minutes)
    return start, end


_DEADLINE_PATTERNS = {
    "ngay_bat_dau": r"Ngày bắt đầu:\s*(\d{2}/\d{2}/\d{4})",
    "ngay_ket_thuc": r"ngày kết thúc:\s*(\d{2}/\d{2}/\d{4})",
    "ngay_nop_ban_diem": r"Ngày nộp bản điểm:\s*(\d{2}/\d{2}/\d{4})",
    "han_dinh_chinh": r"Hạn đính chính điểm:\s*(\d{2}/\d{2}/\d{4})",
}


def parse_grade_deadline(raw_response: str) -> dict[str, str | None]:
    """Trích hạn nhập điểm từ response API LTDICT.

    QUAN TRỌNG: chỉ đọc phần header text nằm TRƯỚC thẻ '<html>' (dạng
    'HH/@/. Hạn nhập điểm: .../@//@/'). Hàm này CỐ TÌNH không đụng tới
    phần bảng '<table id="LTDICT_Grid">' phía sau — bảng đó chứa điểm
    số/tên/mã số sinh viên (dữ liệu cá nhân nhạy cảm của bên thứ ba),
    không liên quan tới việc lấy hạn nộp điểm nên không được parse.
    """
    idx = raw_response.find("<html>")
    header = raw_response[:idx] if idx != -1 else raw_response

    result: dict[str, str | None] = {}
    for key, pat in _DEADLINE_PATTERNS.items():
        m = re.search(pat, header)
        result[key] = m.group(1) if m else None
    return result


def parse_vn_date(date_str: str | None) -> date | None:
    """Chuyển 'dd/mm/yyyy' -> date, hoặc None nếu rỗng/sai định dạng."""
    if not date_str:
        return None
    try:
        d, m, y = date_str.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def parse_class_list(html: str) -> list[dict[str, Any]]:
    """Phân tích danh sách lớp học phần phụ trách (API ctrlLopHP).

    Trả về mã lớp (MHP - dùng để tra hạn nộp điểm theo từng lớp qua
    ctrlListHP), tên lớp, và có phải lớp thi chung hay không.
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="LopHP_Grid")
    if table is None:
        return []

    results: list[dict[str, Any]] = []
    for tr in table.find_all("tr", class_="GridRow"):
        onclick = tr.get("onclick", "")
        m = re.search(r"jLoadLopHP\('(\d+)'\)", onclick)
        if not m:
            continue
        tds = tr.find_all("td")
        texts = [td.get_text(strip=True) for td in tds]
        if len(texts) < 3:
            continue

        thi_chung_cell = tr.find("td", class_="GridCellCenterCheck")
        thi_chung = bool(thi_chung_cell and thi_chung_cell.find("span"))

        results.append(
            {
                "ma_lop": m.group(1),
                "ma_lop_display": texts[1],
                "ten_lop": texts[2],
                "thi_chung": thi_chung,
            }
        )

    return results


_CLASS_DEADLINE_DATE_PATTERNS = {
    "ngay_giua_ky": r"Điểm giữa kỳ:\s*<b>\s*(?:ngày\s*(\d{2}/\d{2}/\d{4})|Chưa thiết lập)",
    "ngay_thanh_phan": r"Điểm thành phần:\s*<b>\s*(?:ngày\s*(\d{2}/\d{2}/\d{4})|Chưa thiết lập)",
    "ngay_cuoi_ky": r"Điểm cuối kỳ:\s*<b>\s*(?:ngày\s*(\d{2}/\d{2}/\d{4})|Chưa thiết lập)",
}
_CLASS_DEADLINE_CORRECTION_PATTERNS = {
    "han_dinh_chinh_giua_ky": r"Hạn đính chính điểm giữa kỳ:</b></font><b>\s*(?:ngày\s*(\d{2}/\d{2}/\d{4})|\s*Chưa)",
    "han_dinh_chinh_thanh_phan": r"Hạn đính chính điểm thành phần:</b></font><b>\s*(?:ngày\s*(\d{2}/\d{2}/\d{4})|\s*Chưa)",
}


def parse_class_deadline(raw_response: str) -> dict[str, str | None]:
    """Trích hạn nhập điểm GIỮA KỲ/THÀNH PHẦN theo TỪNG LỚP (API ctrlListHP).

    Khác với parse_grade_deadline (hạn điểm CUỐI KỲ THI CHUNG theo ca
    thi) — hàm này đọc hạn điểm giữa kỳ/thành phần, vốn khác nhau theo
    từng lớp học phần cụ thể, không phải chung cho cả học kỳ.

    QUAN TRỌNG: chỉ đọc phần header TRƯỚC thẻ '<html>'. Response đầy đủ
    còn chứa bảng điểm/tên/mã số sinh viên (giống parse_grade_deadline)
    — CỐ TÌNH không đụng tới, không parse phần bảng đó.
    """
    idx = raw_response.find("<html>")
    header = raw_response[:idx] if idx != -1 else raw_response

    ma_lop_m = re.search(r"Hạn nhập điểm của lớp:\s*(\d+)", header)
    result: dict[str, str | None] = {
        "ma_lop": ma_lop_m.group(1) if ma_lop_m else None,
    }
    for key, pat in _CLASS_DEADLINE_DATE_PATTERNS.items():
        m = re.search(pat, header)
        result[key] = m.group(1) if m and m.group(1) else None
    for key, pat in _CLASS_DEADLINE_CORRECTION_PATTERNS.items():
        m = re.search(pat, header)
        result[key] = m.group(1) if m and m.group(1) else None

    return result


def parse_hoc_ky_options(html: str) -> list[dict[str, Any]]:
    """Lấy danh sách học kỳ thật từ dropdown '<select id="DKCT_cboHocKy">'
    có sẵn trên trang PageCNDKCoiThi.aspx — dùng để hiển thị cho người
    dùng chọn bằng tên (vd 'Học kỳ 2 năm học 2025-2026') thay vì phải
    tự gõ mã số (vd '2520').
    """
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", id="DKCT_cboHocKy")
    if select is None:
        return []

    return [
        {
            "value": opt.get("value", ""),
            "label": opt.get_text(strip=True),
            "selected": opt.has_attr("selected"),
        }
        for opt in select.find_all("option")
        if opt.get("value")
    ]


def exam_hash(entry: dict[str, Any]) -> str:
    """Mã băm ổn định cho 1 ca thi, dùng để chống báo trùng."""
    raw = "|".join(
        [
            entry.get("ma_ca_thi", ""),
            entry.get("thoi_gian_raw", ""),
            entry.get("phong", ""),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
