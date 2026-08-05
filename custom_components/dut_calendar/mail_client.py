"""Đọc email qua IMAP và lọc theo nhóm từ khóa.

Tách riêng khỏi coordinator để unit-test được không cần Home Assistant.
Toàn bộ hàm ở đây là ĐỒNG BỘ (imaplib chặn luồng) — coordinator phải
gọi qua async_add_executor_job.
"""
from __future__ import annotations

import email
import imaplib
import re
import unicodedata
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from datetime import datetime
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
_RE_THOI_GIAN = re.compile(r"^\s*Th[ờo]i\s*gian\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_DIA_DIEM = re.compile(r"^\s*[ĐD][ịi]a\s*[đd]i[ểe]m\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
_RE_THANH_PHAN = re.compile(r"^\s*Th[àa]nh\s*ph[ầa]n\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# 14h30 | 14h | 14:30 | 14 giờ 30
_RE_GIO = re.compile(r"(\d{1,2})\s*(?:h|:|gi[ờo])\s*(\d{2})?", re.IGNORECASE)
# ngày 4/8/2026 | 04/08/2026 | 4-8-2026
_RE_NGAY = re.compile(r"(\d{1,2})\s*[/-]\s*(\d{1,2})\s*[/-]\s*(\d{4})")


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

    m_ngay = _RE_NGAY.search(raw)
    m_gio = _RE_GIO.search(raw)
    if not m_ngay or not m_gio:
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
