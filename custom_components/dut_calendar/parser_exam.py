"""Logic phân tích HTML của cổng cb.dut.udn.vn (thuần Python, dễ test độc lập)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
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

        texts = [unicodedata.normalize("NFC", td.get_text(strip=True)) for td in tds]
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
        texts = [unicodedata.normalize("NFC", td.get_text(strip=True)) for td in tds]
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


def build_deadline_events(grade_deadlines: dict[str, Any]) -> list[dict[str, Any]]:
    """Gộp phẳng mọi mốc hạn nộp điểm (thi chung + từng lớp) thành 1
    danh sách sự kiện có ngày cụ thể — dùng chung cho Calendar 'Nhập
    điểm' và các sensor đếm số sự kiện (hôm nay/ngày mai/tháng này).
    """
    events: list[dict[str, Any]] = []

    label_ca_thi_chung = {
        "ngay_bat_dau": "Bắt đầu nhập điểm thi chung",
        "ngay_ket_thuc": "Kết thúc nhập điểm thi chung",
        "ngay_nop_ban_diem": "Nộp bản điểm thi chung",
        "han_dinh_chinh": "Hạn đính chính điểm thi chung",
    }
    label_theo_lop = {
        "ngay_giua_ky": "Hạn điểm giữa kỳ",
        "ngay_thanh_phan": "Hạn điểm thành phần",
        "ngay_cuoi_ky": "Hạn điểm cuối kỳ",
        "han_dinh_chinh_giua_ky": "Đính chính điểm giữa kỳ",
        "han_dinh_chinh_thanh_phan": "Đính chính điểm thành phần",
    }

    for hoc_ky, hk_info in (grade_deadlines or {}).items():
        ca_thi_chung = hk_info.get("ca_thi_chung") or {}
        for key, label in label_ca_thi_chung.items():
            d = parse_vn_date(ca_thi_chung.get(key))
            if d:
                events.append({"date": d, "summary": label, "hoc_ky": hoc_ky})

        for ma_lop, info in hk_info.get("theo_lop", {}).items():
            ten_lop = info.get("ten_lop") or ma_lop
            for key, label in label_theo_lop.items():
                d = parse_vn_date(info.get(key))
                if d:
                    events.append(
                        {
                            "date": d,
                            "summary": f"{ten_lop}: {label}",
                            "hoc_ky": hoc_ky,
                            "ma_lop": ma_lop,
                        }
                    )

    return events


def infer_self_name(own_duties: list[dict[str, Any]]) -> str | None:
    """Suy luận tên hiển thị của TÀI KHOẢN ĐANG ĐĂNG NHẬP từ danh sách
    ca thi CỦA CHÍNH MÌNH (DDK=true) — vì "Cán bộ 1"/"Cán bộ 2" không
    cố định vị trí (có ca mình là CB1, có ca mình là CB2, tùy ai đăng
    ký trước), KHÔNG thể giả định vị trí cố định.

    Suy luận: tên của chính mình là tên DUY NHẤT xuất hiện ở MỌI dòng
    (ở CB1 hoặc CB2, không quan trọng vị trí) — vì mọi ca trong danh
    sách "của chính mình" chắc chắn có mình tham gia, còn người cùng
    coi thi thì đổi khác nhau tuỳ ca.

    Trả về None nếu không đủ dữ liệu hoặc không suy luận được rõ ràng
    (vd danh sách rỗng, hoặc nhiều hơn 1 tên khớp mọi dòng).
    """
    rows = [
        {d.get("can_bo_1", "").strip(), d.get("can_bo_2", "").strip()} - {""}
        for d in own_duties
    ]
    rows = [r for r in rows if r]
    if not rows:
        return None
    common = set.intersection(*rows)
    if len(common) == 1:
        return next(iter(common))
    return None


def duty_role(duty: dict[str, Any], target_name: str | None) -> str | None:
    """Xác định vai trò của `target_name` trong 1 ca thi: '1' nếu là
    Cán bộ 1, '2' nếu là Cán bộ 2, None nếu không khớp cả hai (hoặc
    target_name rỗng).
    """
    if not target_name:
        return None
    name = unicodedata.normalize("NFC", target_name.strip().lower())
    if unicodedata.normalize("NFC", duty.get("can_bo_1", "").strip().lower()) == name:
        return "1"
    if unicodedata.normalize("NFC", duty.get("can_bo_2", "").strip().lower()) == name:
        return "2"
    return None


def filter_exam_duty_by_lecturer(
    entries: list[dict[str, Any]], lecturer_name: str
) -> list[dict[str, Any]]:
    """(Cũ, giữ tương thích ngược cho cấu hình dạng text tự do) Lọc theo
    1 tên, kiểu chuỗi con. Cấu hình mới nên dùng
    filter_exam_duty_by_lecturers (khớp chính xác từ danh sách thật).
    """
    name = unicodedata.normalize("NFC", lecturer_name.strip().lower())
    if not name:
        return []

    return [
        e
        for e in entries
        if name in e.get("can_bo_1", "").lower() or name in e.get("can_bo_2", "").lower()
    ]


def filter_exam_duty_by_lecturers(
    entries: list[dict[str, Any]], lecturer_names: list[str]
) -> list[dict[str, Any]]:
    """Lọc ca thi theo DANH SÁCH tên đã chọn từ UI (khớp CHÍNH XÁC,
    không phải chuỗi con) — an toàn hơn filter_exam_duty_by_lecturer
    vì tên lấy trực tiếp từ danh sách thật trên trang, không gõ tay
    nên không có sai sót/trùng lặp ngoài ý muốn.
    """
    normalized = {
        unicodedata.normalize("NFC", n.strip().lower()) for n in lecturer_names if n.strip()
    }
    if not normalized:
        return []

    return [
        e
        for e in entries
        if unicodedata.normalize("NFC", e.get("can_bo_1", "").strip().lower()) in normalized
        or unicodedata.normalize("NFC", e.get("can_bo_2", "").strip().lower()) in normalized
    ]


def build_lecturer_directory(duties: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Từ danh sách ca thi TOÀN BỘ (fetch_exam_duty_all_html), gom các
    tên "Cán bộ 1"/"Cán bộ 2" duy nhất, nhóm theo mã khoa (tiền tố
    trước dấu '-', vd '103-Lê Minh Tiến' -> khoa '103'). Dùng để hiển
    thị UI chọn khoa -> chọn tên thay vì gõ tay.
    """
    names: set[str] = set()
    for d in duties:
        for key in ("can_bo_1", "can_bo_2"):
            n = (d.get(key) or "").strip()
            if n:
                names.add(n)

    khoa_map: dict[str, list[str]] = {}
    for n in names:
        m = re.match(r"^(\d{2,3})-", n)
        code = m.group(1) if m else "khac"
        khoa_map.setdefault(code, []).append(n)

    for code in khoa_map:
        khoa_map[code].sort()

    return khoa_map


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
