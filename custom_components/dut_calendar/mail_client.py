"""Đọc email qua IMAP và lọc theo nhóm từ khóa.

Tách riêng khỏi coordinator để unit-test được không cần Home Assistant.
Toàn bộ hàm ở đây là ĐỒNG BỘ (imaplib chặn luồng) — coordinator phải
gọi qua async_add_executor_job.
"""
from __future__ import annotations

import email
import imaplib
import json
import re
import unicodedata
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from datetime import date, datetime
from typing import Any

from .parser_public import _variant_matches


def decode_mime(raw: str | None) -> str:
    """Giải mã header MIME (Subject/From) về chuỗi đọc được, chuẩn NFC.

    Header tiếng Việt thường mã hóa base64/quoted-printable; nếu không
    giải mã sẽ ra dạng '=?UTF-8?B?...?=' và lọc từ khóa luôn trượt.
    """
    if not raw:
        return ""
    try:
        text = str(make_header(decode_header(raw)))
    except Exception:  # noqa: BLE001
        text = str(raw)
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.replace("\r", " ").replace("\n", " ").split()).strip()


def extract_body(msg: email.message.Message, max_chars: int = 20000) -> str:
    """Lấy phần text của email (ưu tiên text/plain, bỏ qua đính kèm)."""
    parts: list[str] = []

    def _decode(part: email.message.Message) -> str:
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                return ""
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="ignore")
        except Exception:  # noqa: BLE001
            return ""

    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if "attachment" in str(part.get("Content-Disposition", "")).lower():
                continue
            if part.get_content_type() == "text/plain":
                parts.append(_decode(part))
        if not parts:  # không có text/plain -> đành lấy text/html thô
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    parts.append(_decode(part))
    else:
        parts.append(_decode(msg))

    text = unicodedata.normalize("NFC", "\n".join(parts))
    return text[:max_chars]


def message_to_dict(msg: email.message.Message) -> dict[str, Any]:
    """Chuyển email thành dict phẳng để lọc/hiển thị."""
    received: datetime | None = None
    try:
        received = parsedate_to_datetime(msg.get("Date"))
    except Exception:  # noqa: BLE001
        received = None

    return {
        "message_id": (msg.get("Message-ID") or "").strip(),
        "sender": decode_mime(msg.get("From")),
        "to": decode_mime(msg.get("To")),
        "subject": decode_mime(msg.get("Subject")),
        "body": extract_body(msg),
        "received": received,
    }


def filter_mails_by_keywords(
    mails: list[dict[str, Any]], groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Lọc email theo nhóm từ khóa — dùng CHUNG cơ chế so khớp với lịch
    tuần (biến thể viết tắt khớp theo ranh giới từ + phân biệt hoa
    thường; biến thể thường khớp chuỗi con, không phân biệt hoa thường).

    Tìm trong: người gửi + tiêu đề + nội dung.
    """
    result: list[dict[str, Any]] = []

    for m in mails:
        haystack = "\n".join(
            [m.get("sender", ""), m.get("subject", ""), m.get("body", "")]
        )
        haystack = unicodedata.normalize("NFC", haystack)
        lower = haystack.lower()

        matched_labels: list[str] = []
        matched_variants: list[str] = []
        for g in groups:
            hit = [v for v in g["variants"] if _variant_matches(v, haystack, lower)]
            if hit:
                matched_labels.append(g["label"])
                matched_variants.extend(hit)

        if matched_labels:
            result.append(
                {**m, "matched_keywords": matched_labels, "matched_variants": matched_variants}
            )

    return result


def parse_exclude_subjects(raw: str) -> list[str]:
    """Phân tích cấu hình "tiêu đề loại trừ" nhiều dòng — mỗi dòng 1
    cụm. Mail có TIÊU ĐỀ chứa 1 trong các cụm này sẽ bị bỏ qua HOÀN
    TOÀN, không xét khớp từ khóa nữa — dùng cho mail lặp lại đều đặn,
    đã có sẵn ở nguồn khác (vd "Lịch công tác tuần" đã có trong
    `dut_lichtuan`) nên không cần báo lại qua `dut_mail`.
    """
    out: list[str] = []
    raw = unicodedata.normalize("NFC", raw or "")
    for line in raw.replace(";", "\n").splitlines():
        cum = line.strip()
        if cum:
            out.append(cum)
    return out


def exclude_mails_by_subject(
    mails: list[dict[str, Any]], exclude_phrases: list[str]
) -> list[dict[str, Any]]:
    """Bỏ các mail có TIÊU ĐỀ chứa 1 trong `exclude_phrases` (khớp chuỗi
    con, không phân biệt hoa/thường, chuẩn hóa NFC) — áp dụng TRƯỚC khi
    lọc từ khóa, để mail loại trừ không tính vào bất kỳ nhóm nào.

    KHÔNG bao giờ raise — 1 mail có dữ liệu bất thường (subject None,
    kiểu lạ...) chỉ bị bỏ qua bước loại trừ cho riêng nó (coi như
    không loại), không được làm hỏng cả danh sách còn lại.
    """
    if not exclude_phrases:
        return mails
    try:
        phrases_lower = [
            unicodedata.normalize("NFC", str(p)).lower() for p in exclude_phrases if p
        ]
    except Exception:  # noqa: BLE001
        return mails
    if not phrases_lower:
        return mails

    out: list[dict[str, Any]] = []
    for m in mails:
        try:
            subject_raw = m.get("subject") or ""
            subject = unicodedata.normalize("NFC", str(subject_raw)).lower()
            if any(p in subject for p in phrases_lower):
                continue
        except Exception:  # noqa: BLE001
            pass  # lỗi riêng mail này -> coi như không loại, vẫn giữ lại
        out.append(m)
    return out


def fetch_recent_mails(
    host: str,
    port: int,
    username: str,
    password: str,
    folder: str = "INBOX",
    limit: int = 50,
    unseen_only: bool = False,
) -> list[dict[str, Any]]:
    """Kết nối IMAP, lấy `limit` email MỚI NHẤT của thư mục.

    `unseen_only=False` (mặc định): lấy N mail GẦN NHẤT rồi khử trùng
    theo Message-ID ở coordinator — an toàn nhất, không bỏ sót.

    `unseen_only=True`: chỉ lấy mail CHƯA ĐỌC. Nhẹ hơn nhiều nếu hộp
    thư lớn, NHƯNG có rủi ro: mail nào bạn mở trên điện thoại/máy tính
    trước khi HA kịp quét sẽ thành "đã đọc" và bị BỎ SÓT vĩnh viễn.

    Hai tham số kết hợp theo kiểu VÀ: lọc UNSEEN trước, rồi mới cắt
    lấy `limit` mail mới nhất trong số đó.

    Cả 2 chế độ đều KHÔNG đánh dấu đã đọc và KHÔNG xóa mail.
    """
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(username, password)
        # readonly=True: tuyệt đối không làm thay đổi trạng thái hộp thư
        conn.select(folder, readonly=True)

        typ, data = conn.search(None, "UNSEEN" if unseen_only else "ALL")
        if typ != "OK" or not data or not data[0]:
            return []

        ids = data[0].split()
        ids = ids[-limit:] if limit > 0 else ids

        mails: list[dict[str, Any]] = []
        for num in reversed(ids):  # mới nhất trước
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            mails.append(message_to_dict(email.message_from_bytes(raw)))
        return mails
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def mail_stable_id(m: dict[str, Any]) -> str:
    """Khóa định danh mail. Ưu tiên Message-ID (chuẩn, duy nhất toàn
    cầu); nếu server không trả thì rơi về (người gửi + tiêu đề + ngày).
    """
    mid = (m.get("message_id") or "").strip()
    if mid:
        return mid
    received = m.get("received")
    stamp = received.isoformat() if isinstance(received, datetime) else ""
    return f"{m.get('sender','')}|{m.get('subject','')}|{stamp}"


# =====================================================================
# Tách thông tin cuộc họp từ nội dung mail (không dùng AI)
# =====================================================================
# Mail mời họp của trường theo khuôn rất ổn định:
#     Thời gian: 14h30 ngày 4/8/2026 (Thứ 3)
#     Địa điểm: Văn phòng Khoa (A123)
#     Thành phần: ...
#
# BẪY QUAN TRỌNG: mail trả lời/đính chính có TRÍCH LẠI mail cũ bên
# dưới, trong đó ghi giờ CŨ đã bị thay. Vì vậy luôn lấy lần xuất hiện
# ĐẦU TIÊN (phần trên cùng = nội dung mới nhất), không quét cả bài rồi
# lấy kết quả cuối.
_RE_THOI_GIAN = re.compile(r"^\s*[•\-\*\t ]*Th[ờo]i\s*gian\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_DIA_DIEM = re.compile(r"^\s*[•\-\*\t ]*[ĐD][ịi]a\s*[đd]i[ểe]m[^:\n]{0,20}:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_THANH_PHAN = re.compile(r"^\s*Th[àa]nh\s*ph[ầa]n\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# 14h30 | 14h | 14:30 | 14 giờ 30
_RE_GIO = re.compile(r"(\d{1,2})\s*(?:h|:|gi[ờo])\s*(\d{2})?", re.IGNORECASE)
# ngày 4/8/2026 | 04/08/2026 | 4-8-2026
_RE_NGAY = re.compile(r"(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{4})")
# ngày kiểu ISO: 2026-07-26 (tạp chí, hệ thống tự sinh hay dùng)
_RE_NGAY_ISO = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


# 22–23/10/2026 | 22-23/10/2026 : khoảng NGÀY trong cùng tháng
_RE_KHOANG_NGAY = re.compile(
    r"(\d{1,2})\s*[–—-]\s*(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{4})"
)

# "+ Đợt 1: từ ngày 20/04/2026 - 23/04/2026 (...)" — khoảng ngày ĐẦY ĐỦ
# ở cả 2 đầu (khác tháng/năm cũng bắt được), KHÔNG cần nhãn "Thời gian:"
# đứng trước — mail thông báo lịch (sinh hoạt lớp, tập huấn...) hay ghi
# kiểu liệt kê "Đợt X: từ ngày ... - ...:" chứ không dùng khuôn
# "Thời gian:" chuẩn.
#
# BẮT BUỘC có ký hiệu liệt kê (+/-/•/*) đứng đầu dòng VÀ dấu hai chấm
# sau nhãn — nếu không, câu văn mô tả bối cảnh (vd "Đợt xét học vụ 1
# diễn ra từ ngày X đến Y sẽ...") dễ bị bắt nhầm do email bị xuống
# dòng tự nhiên theo độ rộng cột, khiến "từ ngày..." vô tình rơi vào
# đầu 1 dòng dù không phải mục liệt kê thật.
_RE_KHOANG_TU_NGAY = re.compile(
    r"^[ \t]*[+\-•\*\u2022]\s*([^:\n]{1,40}?):\s*t[ừu]\s+ngày\s+"
    r"(\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4})\s*(?:[–—-]|đến|den)\s*(?:ngày\s*)?"
    r"(\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4})",
    re.IGNORECASE | re.MULTILINE,
)

# "... trước 17h00 ngày 29/04/2026 (đợt 1) VÀ 22/05/2026 (đợt 2)." — mốc
# hạn thứ 2 KẾ THỪA giờ của mốc hạn đứng trước trong cùng câu (mail chỉ
# nêu giờ 1 lần dùng chung cho nhiều đợt).
_RE_VA_NGAY = re.compile(
    r"v[àa]\s+(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4})",
    re.IGNORECASE,
)


def _tim_khoang_ngay(text: str) -> tuple[date, date] | None:
    """'22–23/10/2026' -> (22/10/2026, 23/10/2026)."""
    m = _RE_KHOANG_NGAY.search(text or "")
    if not m:
        return None
    try:
        d1 = date(int(m.group(4)), int(m.group(3)), int(m.group(1)))
        d2 = date(int(m.group(4)), int(m.group(3)), int(m.group(2)))
    except ValueError:
        return None
    return (d1, d2) if d2 >= d1 else (d2, d1)


def _tim_ngay(text: str) -> date | None:
    """Tìm ngày đầu tiên trong chuỗi, chấp nhận cả dd/mm/yyyy lẫn ISO."""
    m = _RE_NGAY_ISO.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _RE_NGAY.search(text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def parse_meeting_info(
    body: str, fallback_year: int | None = None
) -> dict[str, Any]:
    """Tách thời gian/địa điểm/thành phần cuộc họp từ thân mail.

    Trả về dict có `start` (datetime, giờ địa phương, không tzinfo),
    `location`, `participants`, kèm chuỗi gốc để đối chiếu. Trường nào
    không tách được thì để None — KHÔNG đoán bừa.
    """
    result: dict[str, Any] = {
        "thoi_gian_raw": None,
        "dia_diem_raw": None,
        "thanh_phan_raw": None,
        "start": None,
        # Sự kiện chỉ ghi NGÀY (hội thảo 2 ngày, không nêu giờ) -> cả ngày
        "all_day_start": None,
        "all_day_end": None,
        "location": None,
    }
    if not body:
        return result

    m_tg = _RE_THOI_GIAN.search(body)  # lần đầu tiên = nội dung mới nhất
    m_dd = _RE_DIA_DIEM.search(body)
    m_tp = _RE_THANH_PHAN.search(body)

    if m_dd:
        result["dia_diem_raw"] = m_dd.group(1).strip()
        result["location"] = result["dia_diem_raw"]
    if m_tp:
        result["thanh_phan_raw"] = m_tp.group(1).strip()

    if not m_tg:
        return result

    raw = m_tg.group(1).strip()
    result["thoi_gian_raw"] = raw

    m_gio = _RE_GIO.search(raw)

    # Không có giờ -> thử khoảng ngày, rồi tới ngày đơn (sự kiện cả ngày)
    if not m_gio:
        khoang = _tim_khoang_ngay(raw)
        if khoang:
            result["all_day_start"], result["all_day_end"] = khoang
        else:
            d = _tim_ngay(raw)
            if d:
                result["all_day_start"] = result["all_day_end"] = d
        return result

    m_ngay = _RE_NGAY.search(raw)
    if not m_ngay:
        return result

    try:
        day, month, year = int(m_ngay.group(1)), int(m_ngay.group(2)), int(m_ngay.group(3))
        hour = int(m_gio.group(1))
        minute = int(m_gio.group(2) or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return result
        result["start"] = datetime(year, month, day, hour, minute)
    except ValueError:
        return result

    return result


_RE_TIEN_TO_TIEU_DE = re.compile(r"^\s*(?:fw|fwd|re|tr|v/v)\s*:\s*", re.IGNORECASE)
_RE_NGUOI_GUI_GOC = re.compile(
    r"^\s*(?:T[ừu]|From)\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE
)


def normalize_subject(subject: str) -> str:
    """Bỏ các tiền tố Fw:/Fwd:/Re:/... (kể cả lồng nhau) để nhận ra
    các mail cùng nói về MỘT cuộc họp.
    """
    s = unicodedata.normalize("NFC", subject or "").strip()
    while True:
        new = _RE_TIEN_TO_TIEU_DE.sub("", s, count=1).strip()
        if new == s:
            return s
        s = new


def extract_original_sender(body: str) -> str | None:
    """Lấy NGƯỜI GỬI GỐC từ phần trích dẫn của mail chuyển tiếp.

    Khi mail được forward (vd bạn tự forward từ Outlook trường sang
    Gmail), header From là người CHUYỂN TIẾP chứ không phải người gửi
    thật. Người gửi gốc nằm ở dòng "Từ:"/"From:" đầu tiên trong thân.
    """
    if not body:
        return None
    m = _RE_NGUOI_GUI_GOC.search(body)
    if not m:
        return None
    val = " ".join(m.group(1).split()).strip()
    return unicodedata.normalize("NFC", val) or None


# Các cụm thường dùng để nêu HẠN CHÓT trong mail (không phải cuộc họp)
_RE_HAN = re.compile(
    # Từ khóa báo hiệu HẠN, cho phép vài chữ đệm trước ngày
    # ("Hạn nộp chậm nhất ngày 9/8/2026", "trước ngày 2026-08-06").
    # "trước" đứng một mình cũng tính, để bắt "trước 11h00 ngày 12/8/2026";
    # vẫn an toàn vì bắt buộc phải có NGÀY trong vòng 25 ký tự sau đó.
    r"(?:tr[ưu][ớo]c|ch[ậa]m\s+nh[ấa]t|"
    r"h[ạa]n\s+(?:ch[óo]t|cu[ốo]i|n[ộo]p|[đd][ăa]ng\s*k[ýy]|g[ửu]i))"
    r"[^.\n]{0,25}?"
    r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4})",
    re.IGNORECASE,
)

# Dấu hiệu bắt đầu phần TRÍCH DẪN mail cũ trong mail chuyển tiếp
_RE_DAU_TRICH_DAN = re.compile(
    r"^\s*(?:T[ừu]|From)\s*:|^\s*_{5,}\s*$|^\s*-{5,}\s*$", re.MULTILINE
)


def phan_moi_nhat(body: str) -> str:
    """Cắt bỏ phần trích dẫn mail cũ, chỉ giữ nội dung MỚI NHẤT ở trên.

    Mail chuyển tiếp thường kèm nguyên mail gốc bên dưới, trong đó có
    mốc thời gian CŨ hoặc mốc của đơn vị khác — vd Khoa chuyển tiếp
    thông báo của Phòng và đặt hạn nộp về Khoa (9/8) SỚM HƠN hạn của
    Phòng (10/8). Hạn áp dụng cho người nhận là hạn ở phần trên.
    """
    if not body:
        return body
    m = _RE_DAU_TRICH_DAN.search(body)
    return body[: m.start()] if m else body


def parse_deadlines(body: str, max_items: int = 5) -> list[dict[str, Any]]:
    """Tìm các mốc HẠN CHÓT trong mail (mail mời phản biện, mời nộp
    hồ sơ... thường không có dòng "Thời gian:" mà chỉ nêu "trước ngày X").

    Trả về danh sách {date, context} — `context` là câu chứa mốc đó, để
    biết hạn này là hạn gì (xác nhận / nộp bài / ...). Khử trùng theo
    ngày, giữ ngữ cảnh của lần xuất hiện đầu tiên.

    Mốc "và ngày Y (đợt 2)" đứng ngay sau 1 mốc "trước GIỜ ngày X" trong
    CÙNG câu được coi là hạn thứ 2, KẾ THỪA giờ của mốc đứng trước (mail
    chỉ nêu giờ một lần dùng chung cho nhiều đợt) — không phải suy đoán,
    chỉ áp dụng khi nằm chung câu với 1 hạn đã xác nhận.
    """
    if not body:
        return []

    ket_qua: list[dict[str, Any]] = []
    da_co: set[date] = set()

    # Ưu tiên phần mới nhất; nếu phần đó không có mốc nào (mail thuần
    # chuyển tiếp, không thêm chữ) thì mới quét toàn bộ.
    pham_vi = phan_moi_nhat(body)
    if not _RE_HAN.search(pham_vi):
        pham_vi = body

    for m in _RE_HAN.finditer(pham_vi):
        d = _tim_ngay(m.group(1))
        if d is None or d in da_co:
            continue
        da_co.add(d)

        # Lấy câu chứa mốc hạn làm ngữ cảnh
        dau = pham_vi.rfind(".", 0, m.start())
        cuoi = pham_vi.find(".", m.end())
        cau = pham_vi[(dau + 1 if dau != -1 else 0) : (cuoi if cuoi != -1 else len(pham_vi))]
        cau = " ".join(cau.split()).strip()

        # Hạn có thể kèm GIỜ: "trước 11h00 ngày 12/8/2026" -> 11:00
        gio = None
        m_gio = _RE_GIO.search(m.group(0))
        if m_gio:
            h, p = int(m_gio.group(1)), int(m_gio.group(2) or 0)
            if 0 <= h <= 23 and 0 <= p <= 59:
                gio = f"{h:02d}:{p:02d}"

        ket_qua.append({"date": d, "gio": gio, "context": cau[:200]})
        if len(ket_qua) >= max_items:
            break

        # Mốc phụ "... và ngày Y (...)" trong CÙNG câu -> hạn thứ 2, kế
        # thừa giờ của mốc vừa tìm ở trên.
        for m_va in _RE_VA_NGAY.finditer(cau):
            d_va = _tim_ngay(m_va.group(1))
            if d_va is None or d_va in da_co:
                continue
            da_co.add(d_va)
            ket_qua.append({"date": d_va, "gio": gio, "context": cau[:200]})
            if len(ket_qua) >= max_items:
                break

    return ket_qua[:max_items]


def parse_date_ranges(body: str, max_items: int = 5) -> list[dict[str, Any]]:
    """Tìm các khoảng "từ ngày X - Y" KHÔNG cần nhãn "Thời gian:" đứng
    trước — mail thông báo dạng liệt kê (sinh hoạt lớp, tập huấn nhiều
    đợt...) hay ghi "Đợt N: từ ngày ... - ..." thay vì khuôn chuẩn.

    Trả về danh sách {start, end, context} — mỗi khoảng thành 1 sự kiện
    CẢ NGÀY riêng (khác _tim_khoang_ngay chỉ lấy 1 khoảng duy nhất theo
    sau nhãn "Thời gian:").
    """
    if not body:
        return []

    ket_qua: list[dict[str, Any]] = []
    da_co: set[tuple[date, date]] = set()

    pham_vi = phan_moi_nhat(body)
    if not _RE_KHOANG_TU_NGAY.search(pham_vi):
        pham_vi = body

    for m in _RE_KHOANG_TU_NGAY.finditer(pham_vi):
        d1 = _tim_ngay(m.group(2))
        d2 = _tim_ngay(m.group(3))
        if d1 is None or d2 is None:
            continue
        if d2 < d1:
            d1, d2 = d2, d1
        if (d1, d2) in da_co:
            continue
        da_co.add((d1, d2))

        nhan = " ".join((m.group(1) or "").split()).strip()
        ket_qua.append({"start": d1, "end": d2, "context": nhan[:60]})
        if len(ket_qua) >= max_items:
            break

    return ket_qua


# Dòng dạng "Nhãn: <ngày>" trong danh sách mốc thời gian, vd:
#   • Hạn nộp tóm tắt (Abstract): 31/8/2026;
_RE_MOC_THOI_GIAN = re.compile(
    r"^[\s•\-\*\u2022\t]*([^:\n]{3,60}?)\s*:\s*"
    r"(\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4}|\d{4}-\d{1,2}-\d{1,2})\s*[;.,]?\s*$",
    re.MULTILINE,
)
# Không coi các dòng này là "mốc" (đã xử lý riêng ở parse_meeting_info)
_NHAN_BO_QUA = ("thời gian", "thoi gian", "địa điểm", "dia diem", "thành phần", "thanh phan")


def parse_milestones(body: str, max_items: int = 10) -> list[dict[str, Any]]:
    """Tách danh sách mốc thời gian dạng "Nhãn: ngày".

    Mail thông báo hội thảo thường liệt kê nhiều mốc (hạn gửi bài, hạn
    đăng ký, ngày thông báo kết quả...) — mỗi mốc là 1 dòng "Nhãn: ngày".
    Khác với parse_deadlines (bắt cụm "trước ngày ..." nằm trong câu văn).
    """
    if not body:
        return []

    out: list[dict[str, Any]] = []
    da_co: set[tuple[str, date]] = set()

    pham_vi = phan_moi_nhat(body)
    if not _RE_MOC_THOI_GIAN.search(pham_vi):
        pham_vi = body

    for m in _RE_MOC_THOI_GIAN.finditer(pham_vi):
        nhan = " ".join(m.group(1).split()).strip()
        if not nhan:
            continue
        nhan_lower = unicodedata.normalize("NFC", nhan).lower()
        if any(bo in nhan_lower for bo in _NHAN_BO_QUA):
            continue

        d = _tim_ngay(m.group(2))
        if d is None:
            continue

        khoa = (nhan_lower, d)
        if khoa in da_co:
            continue
        da_co.add(khoa)

        out.append({"date": d, "context": nhan})
        if len(out) >= max_items:
            break

    return out


# =====================================================================
# AI hỗ trợ (chỉ gọi khi rule-based KHÔNG tách được gì từ mail đã khớp
# từ khóa) — dùng entity "conversation" có sẵn trong HA, KHÔNG tự gọi
# API/lưu API key riêng trong dut_calendar.
# =====================================================================

_AI_PROMPT_TEMPLATE = """Bạn là bộ trích xuất dữ liệu, KHÔNG phải trợ lý trò chuyện. Đọc email tiếng Việt dưới đây và trả lời DUY NHẤT một khối JSON hợp lệ, không thêm chữ nào khác, không dùng markdown code fence.

Nguyên tắc quan trọng nhất: THÀ ĐỂ TRỐNG (null / mảng rỗng) CÒN HƠN ĐOÁN SAI. Chỉ điền giá trị khi thông tin có ghi RÕ RÀNG trong email. Không suy luận, không tự bịa ngày/giờ/địa điểm.

Cấu trúc JSON cần trả về:
{{
  "start": "YYYY-MM-DDTHH:MM" hoặc null,   // thời điểm CUỘC HỌP/SỰ KIỆN có giờ cụ thể (không phải hạn nộp)
  "location": "chuỗi" hoặc null,             // địa điểm cuộc họp/sự kiện
  "all_day_start": "YYYY-MM-DD" hoặc null,   // nếu sự kiện CẢ NGÀY hoặc nhiều ngày, không ghi giờ
  "all_day_end": "YYYY-MM-DD" hoặc null,
  "deadlines": [                              // các mốc HẠN CHÓT (nộp bài, đăng ký, xác nhận...)
    {{"date": "YYYY-MM-DD", "gio": "HH:MM hoặc null", "context": "mô tả ngắn hạn này là hạn gì"}}
  ],
  "date_ranges": [                            // các khoảng "từ ngày X đến ngày Y" không phải cuộc họp 1 giờ cụ thể
    {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "context": "mô tả ngắn (vd Đợt 1)"}}
  ]
}}

Tiêu đề email: {subject}

Nội dung email (đã cắt bỏ phần trích dẫn cũ nếu có):
{body}
"""


def build_ai_prompt(subject: str, body: str, max_body_chars: int = 4000) -> str:
    """Dựng prompt gửi cho AI conversation agent khi rule-based thất bại.

    Chỉ gửi phần thân mail MỚI NHẤT (đã cắt bỏ trích dẫn mail cũ, giống
    hệt phạm vi rule-based dùng) — không gửi toàn văn nếu có phần cắt.
    """
    phan_moi = phan_moi_nhat(body or "")
    phan_moi = phan_moi[:max_body_chars]
    return _AI_PROMPT_TEMPLATE.format(subject=(subject or "").strip(), body=phan_moi.strip())


_RE_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def parse_ai_response(text: str) -> dict[str, Any]:
    """Parse JSON trả về từ AI thành cùng cấu trúc dữ liệu như rule-based
    (start/all_day_start/all_day_end/location/deadlines/date_ranges).

    KHÔNG bao giờ raise — parse lỗi hoặc thiếu field thì trả kết quả
    rỗng, coi như AI cũng không tìm thấy gì (đúng nguyên tắc "thà trống
    còn hơn sai": AI cũng phải tuân thủ, không được ưu tiên hơn rule).
    """
    result: dict[str, Any] = {
        "start": None,
        "location": None,
        "all_day_start": None,
        "all_day_end": None,
        "deadlines": [],
        "date_ranges": [],
    }
    if not text:
        return result

    m = _RE_JSON_BLOCK.search(text)
    raw = m.group(0) if m else text
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return result
    if not isinstance(data, dict):
        return result

    def _valid_date(s: Any) -> date | None:
        if not isinstance(s, str):
            return None
        try:
            return date.fromisoformat(s[:10])
        except ValueError:
            return None

    def _valid_datetime(s: Any) -> datetime | None:
        if not isinstance(s, str):
            return None
        try:
            return datetime.fromisoformat(s[:16])
        except ValueError:
            return None

    dt = _valid_datetime(data.get("start"))
    if dt:
        result["start"] = dt
        loc = data.get("location")
        if isinstance(loc, str) and loc.strip():
            result["location"] = loc.strip()[:200]

    d1 = _valid_date(data.get("all_day_start"))
    d2 = _valid_date(data.get("all_day_end")) or d1
    if d1 and d2:
        result["all_day_start"], result["all_day_end"] = (d1, d2) if d2 >= d1 else (d2, d1)
        if not result["location"]:
            loc = data.get("location")
            if isinstance(loc, str) and loc.strip():
                result["location"] = loc.strip()[:200]

    for h in (data.get("deadlines") or [])[:5]:
        if not isinstance(h, dict):
            continue
        d = _valid_date(h.get("date"))
        if not d:
            continue
        gio = h.get("gio")
        gio = gio.strip()[:5] if isinstance(gio, str) and re.match(r"^\d{1,2}:\d{2}$", gio.strip()) else None
        ctx = h.get("context")
        result["deadlines"].append(
            {"date": d, "gio": gio, "context": (ctx.strip()[:200] if isinstance(ctx, str) else "")}
        )

    for r in (data.get("date_ranges") or [])[:5]:
        if not isinstance(r, dict):
            continue
        rs = _valid_date(r.get("start"))
        re_ = _valid_date(r.get("end")) or rs
        if not rs or not re_:
            continue
        if re_ < rs:
            rs, re_ = re_, rs
        ctx = r.get("context")
        result["date_ranges"].append(
            {"start": rs, "end": re_, "context": (ctx.strip()[:60] if isinstance(ctx, str) else "")}
        )

    return result
