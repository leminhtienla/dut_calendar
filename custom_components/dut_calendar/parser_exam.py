"""Logic phân tích HTML của cổng cb.dut.udn.vn (thuần Python, dễ test độc lập)."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup

from .const import TIET_DURATION_MINUTES, TIET_START


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


def format_hoc_ky(code: str) -> str:
    """Chuyển mã học kỳ (vd '2521') sang tên đọc được.

    Quy tắc theo TÀI LIỆU CHÍNH THỨC của Phòng Đào tạo (mục 3.1 "Quy
    ước Mã" — phần mã lớp học phần, 4 ký tự mã học kỳ):
      YY S K  →  YY = 2 số cuối của năm ĐẦU trong năm học (25 -> 2025-2026)
                 S  = 1 hoặc 2  : chỉ học kỳ
                 K  = 0 hoặc 1  : chỉ kỳ CHÍNH (0) hay kỳ PHỤ (1)
    Trên giao diện trường, kỳ phụ của học kỳ 2 được gọi là "Học kỳ Hè".
      2510 -> HK1 2025-2026 | 2520 -> HK2 2025-2026 | 2521 -> Hè 2025-2026

    Trả về nguyên mã nếu không khớp định dạng (phòng khi trường đổi
    quy ước mà chưa kịp cập nhật).
    """
    code = (code or "").strip()
    if not re.fullmatch(r"\d{4}", code):
        return code

    yy, s_ky, k_phu = int(code[:2]), code[2], code[3]
    nam_hoc = f"{2000 + yy}-{2000 + yy + 1}"

    if s_ky not in ("1", "2") or k_phu not in ("0", "1"):
        return code

    if k_phu == "1":
        ky = "Hè" if s_ky == "2" else f"{s_ky} (phụ)"
    else:
        ky = s_ky

    return f"Học kỳ {ky} năm học {nam_hoc}"


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
        "han_dinh_chinh_cuoi_ky": "Đính chính điểm cuối kỳ",
        "nop_bang_giua_ky": "Nộp bảng điểm giữa kỳ",
        "nop_bang_thanh_phan": "Nộp bảng điểm thành phần",
        "nop_bang_cuoi_ky": "Nộp bảng điểm cuối kỳ",
        "nop_bang_tong_hop": "Nộp bảng điểm tổng hợp",
    }
    # Mốc nào đã hoàn thành thì lấy cờ từ đâu (nếu có dữ liệu xác nhận)
    done_flag = {
        "ngay_giua_ky": "giua_ky_xong",
        "han_dinh_chinh_giua_ky": "giua_ky_xong",
        "ngay_thanh_phan": "thanh_phan_xong",
        "han_dinh_chinh_thanh_phan": "thanh_phan_xong",
        "ngay_cuoi_ky": "cuoi_ky_xong",
        "han_dinh_chinh_cuoi_ky": "cuoi_ky_xong",
        "nop_bang_giua_ky": "nop_bang_giua_ky_xong",
        "nop_bang_thanh_phan": "nop_bang_thanh_phan_xong",
        "nop_bang_cuoi_ky": "nop_bang_cuoi_ky_xong",
        "nop_bang_tong_hop": "nop_bang_tong_hop_xong",
    }

    for hoc_ky, hk_info in (grade_deadlines or {}).items():
        ca_thi_chung = hk_info.get("ca_thi_chung") or {}
        for key, label in label_ca_thi_chung.items():
            d = parse_vn_date(ca_thi_chung.get(key))
            if d:
                events.append(
                    {
                        "date": d,
                        "summary": label,
                        "hoc_ky": hoc_ky,
                        "ten_lop": None,
                        "nhom": None,
                        "ma_lop": None,
                        "loai": label,
                        "da_xong": bool(ca_thi_chung.get("da_xac_nhan")),
                    }
                )

        for ma_lop, info in hk_info.get("theo_lop", {}).items():
            ten_lop = info.get("ten_lop") or ma_lop
            # Mã lớp 15 chữ số dạng: [7 mã HP][4 mã HK][2 khóa][2 nhóm]
            # vd 103164025202419 -> nhóm "24.19". Cần hiện số nhóm vì
            # nhiều lớp KHÁC NHAU có cùng tên môn (2 nhóm cùng học
            # phần), nếu không sẽ ra 2 dòng trùng hệt nhau trên lịch.
            m = re.fullmatch(r"\d{11}(\d{2})(\d{2})", str(ma_lop))
            nhom = f" (nhóm {m.group(1)}.{m.group(2)})" if m else ""

            for key, label in label_theo_lop.items():
                d = parse_vn_date(info.get(key))
                if d:
                    flag = done_flag.get(key)
                    events.append(
                        {
                            "date": d,
                            "summary": f"{label}: {ten_lop}{nhom}",
                            "hoc_ky": hoc_ky,
                            "ten_lop": ten_lop,
                            "nhom": m.group(1) + "." + m.group(2) if m else None,
                            "ma_lop": ma_lop,
                            "loai": label,
                            "da_xong": bool(info.get(flag)) if flag else False,
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


# =====================================================================
# Trang "Kế hoạch giảng dạy & thi" (PageLichGiangDay) — 1 request duy
# nhất trả về 4 bảng, thay cho việc gọi ctrlLopHP + ctrlListHP cho
# TỪNG lớp (≈11 request/học kỳ) như trước.
#
# LƯU Ý QUAN TRỌNG: các cột dấu ✓ trên trang này RỖNG về mặt text,
# trạng thái nằm ở class CSS của ô:
#   GridCellCenterCheck -> có tick (✓)
#   GridCellDisable     -> ô bị vô hiệu (không áp dụng)
# Đọc theo text sẽ ra sai toàn bộ.
# =====================================================================
def _lgd_rows(table, ncols: int):
    """Lấy các dòng dữ liệu (đúng số cột), bỏ dòng tiêu đề gộp nhiều tầng."""
    out = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) != ncols:
            continue
        vals = [unicodedata.normalize("NFC", c.get_text(" ", strip=True)) for c in cells]
        if not vals[0].isdigit():  # cột TT/STT phải là số
            continue
        out.append((vals, cells))
    return out


def _lgd_checked(td) -> bool:
    return "GridCellCenterCheck" in (td.get("class") or [])


def _lgd_disabled(td) -> bool:
    return "GridCellDisable" in (td.get("class") or [])


def parse_lich_giang_day(html: str) -> dict[str, Any]:
    """Phân tích response của E=ctrLichGiangDay&SKH=<mã học kỳ>."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {
        "lop_hoc": [],
        "nhap_diem_theo_lop": [],
        "nop_bang_diem_rieng": [],
        "thi_chung": [],
    }

    # 1) Lịch giảng dạy trong kỳ (kèm thời khóa biểu)
    tb = soup.find("table", id="LichGiangDay_Grid")
    if tb:
        for v, c in _lgd_rows(tb, 14):
            result["lop_hoc"].append(
                {
                    "ma_lop": v[1],
                    "ten_lop": v[2],
                    "so_tin_chi": v[3],
                    "danh_gia": v[4],
                    "tkb_tuan": v[6] or None,
                    "tkb_thu_tiet_phong": v[7] or None,
                    "lich_trinh_da_nhap": _lgd_checked(c[8]),
                    "lich_trinh_da_nop": _lgd_checked(c[9]),
                }
            )

    # 2) Hạn nhập điểm theo lớp (GK / TP / CK thi riêng)
    tb = soup.find("table", id="LichGiangDay_KiemTra")
    if tb:
        for v, c in _lgd_rows(tb, 19):

            def _block(off: int) -> dict[str, Any]:
                return {
                    "han_nhap_diem": v[off] or None,
                    "han_dinh_chinh": v[off + 1] or None,
                    "xac_nhan_luc": v[off + 2] or None,
                    "gia_han": v[off + 3] or None,
                    "tre_han": v[off + 4] or None,
                }

            result["nhap_diem_theo_lop"].append(
                {
                    "ma_lop": v[1],
                    "ten_lop": v[2],
                    "tuan_thi": v[3] or None,
                    "giua_ky": _block(4),
                    "thanh_phan": _block(9),
                    "cuoi_ky_rieng": _block(14),
                }
            )

    # 3) Nộp bảng in điểm thi riêng
    tb = soup.find("table", id="LichGiangDay_BDTRieng")
    if tb:
        for v, c in _lgd_rows(tb, 15):

            def _blk(off: int) -> dict[str, Any]:
                return {
                    "phai_nop": _lgd_checked(c[off]),
                    "khong_ap_dung": _lgd_disabled(c[off]),
                    "han_nop": v[off + 1] or None,
                    "ngay_nop": v[off + 2] or None,
                }

            result["nop_bang_diem_rieng"].append(
                {
                    "ma_lop": v[1],
                    "ten_lop": v[2],
                    "giua_ky": _blk(3),
                    "thanh_phan": _blk(6),
                    "cuoi_ky": _blk(9),
                    "tong_hop": _blk(12),
                }
            )

    # 4) Thi chung
    tb = soup.find("table", id="LichGiangDay_ThiChung")
    if tb:
        for v, c in _lgd_rows(tb, 13):
            result["thi_chung"].append(
                {
                    "ngay": v[1],
                    "ma_ca_thi": v[2],
                    "phong": v[3],
                    "hoc_phan": v[4],
                    "nhap_diem_bat_dau": v[5] or None,
                    "nhap_diem_ket_thuc": v[6] or None,
                    "gia_han": v[7] or None,
                    "han_dinh_chinh": v[8] or None,
                    "da_xac_nhan": _lgd_checked(c[9]),
                    "ngay_tre_han": v[10] or None,
                    "han_nop_bang": v[11] or None,
                    "da_nop_luc": v[12] or None,
                }
            )

    return result


def lgd_to_grade_deadlines(parsed: dict[str, Any], hoc_ky: str) -> dict[str, Any]:
    """Chuyển kết quả parse_lich_giang_day sang cấu trúc grade_deadlines
    mà coordinator/sensor/calendar đang dùng, BỔ SUNG cờ đã hoàn thành
    (`*_xong`) lấy từ cột "xác nhận lúc" — nhờ đó phân biệt được mốc
    hạn CÒN PHẢI LÀM với mốc ĐÃ NHẬP ĐIỂM XONG.
    """
    theo_lop: dict[str, Any] = {}
    for row in parsed.get("nhap_diem_theo_lop", []):
        gk = row.get("giua_ky") or {}
        tp = row.get("thanh_phan") or {}
        ck = row.get("cuoi_ky_rieng") or {}
        theo_lop[row["ma_lop"]] = {
            "ten_lop": row.get("ten_lop"),
            "tuan_thi": row.get("tuan_thi"),
            "ngay_giua_ky": gk.get("han_nhap_diem"),
            "han_dinh_chinh_giua_ky": gk.get("han_dinh_chinh"),
            "giua_ky_xong": bool(gk.get("xac_nhan_luc")),
            "ngay_thanh_phan": tp.get("han_nhap_diem"),
            "han_dinh_chinh_thanh_phan": tp.get("han_dinh_chinh"),
            "thanh_phan_xong": bool(tp.get("xac_nhan_luc")),
            "ngay_cuoi_ky": ck.get("han_nhap_diem"),
            "han_dinh_chinh_cuoi_ky": ck.get("han_dinh_chinh"),
            "cuoi_ky_xong": bool(ck.get("xac_nhan_luc")),
        }

    # Hạn nộp BẢNG IN điểm (khác hạn NHẬP điểm) — gộp theo mã lớp gốc
    # (bỏ hậu tố A/B của bảng điểm) để hiện cùng lớp tương ứng.
    for row in parsed.get("nop_bang_diem_rieng", []):
        key = re.sub(r"[.\s]", "", row["ma_lop"])
        key = re.sub(r"[A-Z]$", "", key)
        target = theo_lop.setdefault(key, {"ten_lop": row.get("ten_lop")})
        for field, blk in (
            ("nop_bang_giua_ky", row.get("giua_ky")),
            ("nop_bang_thanh_phan", row.get("thanh_phan")),
            ("nop_bang_cuoi_ky", row.get("cuoi_ky")),
            ("nop_bang_tong_hop", row.get("tong_hop")),
        ):
            blk = blk or {}
            han = blk.get("han_nop")
            if blk.get("phai_nop") and han and parse_vn_date(han):
                target[field] = han
                target[f"{field}_xong"] = bool(blk.get("ngay_nop"))

    # Thi chung: lấy mốc chung nhất của học kỳ
    thi_chung_rows = parsed.get("thi_chung", [])
    ca_thi_chung: dict[str, Any] = {}
    if thi_chung_rows:
        first = thi_chung_rows[0]
        ca_thi_chung = {
            "ngay_bat_dau": first.get("nhap_diem_bat_dau"),
            "ngay_ket_thuc": first.get("nhap_diem_ket_thuc"),
            "han_dinh_chinh": first.get("han_dinh_chinh"),
            "ngay_nop_ban_diem": first.get("han_nop_bang"),
            "da_xac_nhan": all(r.get("da_xac_nhan") for r in thi_chung_rows),
            "so_ca": len(thi_chung_rows),
        }

    return {"ca_thi_chung": ca_thi_chung or None, "theo_lop": theo_lop}


# =====================================================================
# Thời khóa biểu -> buổi dạy cụ thể (Calendar "Giảng dạy")
# =====================================================================
def parse_tuan_hoc(raw: str) -> list[int]:
    """'22-27;31-40' -> [22..27, 31..40]. Chấp nhận cả dấu ',' và ';'."""
    weeks: list[int] = []
    for part in re.split(r"[;,]", raw or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            weeks.extend(range(min(a, b), max(a, b) + 1))
        elif part.isdigit():
            weeks.append(int(part))
    return sorted(set(weeks))


def parse_tkb_slots(raw: str) -> list[dict[str, Any]]:
    """'T3,6-7,F109' -> [{'thu':3,'tiet_dau':6,'tiet_cuoi':7,'phong':'F109'}].

    Hỗ trợ nhiều buổi trong tuần, cách nhau bằng ';'. 'CN' = Chủ nhật.
    """
    slots: list[dict[str, Any]] = []
    for part in re.split(r"[;]", raw or ""):
        part = part.strip()
        if not part:
            continue
        m = re.match(
            r"^(?:T(\d+)|CN)\s*,\s*(\d+)(?:\s*-\s*(\d+))?\s*,\s*(.+)$",
            part,
            flags=re.IGNORECASE,
        )
        if not m:
            continue
        thu = 8 if m.group(1) is None else int(m.group(1))  # CN coi như "thứ 8"
        tiet_dau = int(m.group(2))
        tiet_cuoi = int(m.group(3)) if m.group(3) else tiet_dau
        slots.append(
            {
                "thu": thu,
                "tiet_dau": tiet_dau,
                "tiet_cuoi": tiet_cuoi,
                "phong": m.group(4).strip(),
            }
        )
    return slots


def build_teaching_events(
    lop_hoc: list[dict[str, Any]], week_map: dict[int, date]
) -> list[dict[str, Any]]:
    """Dựng danh sách buổi dạy cụ thể (có ngày + giờ) từ thời khóa biểu.

    `week_map` = {số tuần học -> ngày Thứ Hai}, lấy từ dropdown công
    khai của lichtuan.dut.udn.vn (parser_public.parse_all_weeks).

    Giờ bắt đầu/kết thúc suy từ bảng TIET_START trong const.py.
    Tuần nào không có trong week_map (vd lịch trỏ sang năm học khác)
    sẽ được BỎ QUA thay vì đoán bừa ngày.
    """
    events: list[dict[str, Any]] = []

    for lop in lop_hoc:
        weeks = parse_tuan_hoc(lop.get("tkb_tuan") or "")
        slots = parse_tkb_slots(lop.get("tkb_thu_tiet_phong") or "")
        if not weeks or not slots:
            continue

        for w in weeks:
            monday = week_map.get(w)
            if monday is None:
                continue
            for s in slots:
                # Thứ 2 -> offset 0, Thứ 3 -> 1, ..., CN ("thứ 8") -> 6
                offset = s["thu"] - 2
                if not 0 <= offset <= 6:
                    continue
                day = monday + timedelta(days=offset)

                start_hm = TIET_START.get(s["tiet_dau"])
                end_hm = TIET_START.get(s["tiet_cuoi"])
                if not start_hm or not end_hm:
                    continue
                start = datetime(day.year, day.month, day.day, *start_hm)
                end = datetime(day.year, day.month, day.day, *end_hm) + timedelta(
                    minutes=TIET_DURATION_MINUTES
                )

                events.append(
                    {
                        "start": start,
                        "end": end,
                        "ten_lop": lop.get("ten_lop"),
                        "ma_lop": lop.get("ma_lop"),
                        "phong": s["phong"],
                        "tuan": w,
                        "tiet": f"{s['tiet_dau']}-{s['tiet_cuoi']}"
                        if s["tiet_dau"] != s["tiet_cuoi"]
                        else str(s["tiet_dau"]),
                    }
                )

    events.sort(key=lambda e: e["start"])
    return events


def parse_bieu_do_nam_hoc(html: str, hoc_ky: str) -> dict[int, date]:
    """Đọc tab "Biểu đồ thời gian giảng ở năm học"
    (E=ctrLGD_KeHoach&SKH=<mã HK>) -> {số tuần học: ngày Thứ Hai}.

    Bảng có 2 hàng tiêu đề lồng nhau: hàng THÁNG (mỗi ô colspan = số
    tuần trong tháng) và hàng NGÀY (mỗi ô = ngày đầu tuần). Ghép lại
    ra ngày đầy đủ. Năm suy từ mã học kỳ: tháng >= 8 thuộc năm đầu của
    năm học, tháng <= 7 thuộc năm sau.

    Ưu điểm so với đọc từ lichtuan.dut.udn.vn: cùng nguồn với dữ liệu
    thời khóa biểu nên chắc chắn khớp cách đánh số tuần, không phụ
    thuộc trang ngoài.
    """
    if not re.fullmatch(r"\d{4}", (hoc_ky or "").strip()):
        return {}
    start_year = 2000 + int(hoc_ky[:2])

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="ctrLGD_KeHoach_Grid")
    if table is None:
        return {}

    rows = table.find_all("tr")
    if len(rows) < 3:
        return {}

    months: list[int] = []
    for cell in rows[1].find_all(["th", "td"]):
        m = re.search(r"(\d{1,2})", cell.get_text(" ", strip=True))
        if not m:
            continue
        try:
            span = int(cell.get("colspan") or 1)
        except ValueError:
            span = 1
        months.extend([int(m.group(1))] * span)

    days = [c.get_text(strip=True) for c in rows[2].find_all(["th", "td"])]
    if len(months) != len(days):
        return {}

    week_map: dict[int, date] = {}
    for idx, (month, day_txt) in enumerate(zip(months, days), start=1):
        if not day_txt.isdigit():
            continue
        year = start_year if month >= 8 else start_year + 1
        try:
            week_map[idx] = date(year, month, int(day_txt))
        except ValueError:
            continue
    return week_map
