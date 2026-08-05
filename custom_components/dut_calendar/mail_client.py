"""Đọc email qua IMAP và lọc theo nhóm từ khóa.

Tách riêng khỏi coordinator để unit-test được không cần Home Assistant.
Toàn bộ hàm ở đây là ĐỒNG BỘ (imaplib chặn luồng) — coordinator phải
gọi qua async_add_executor_job.
"""
from __future__ import annotations

import email
import imaplib
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
) -> list[dict[str, Any]]:
    """Kết nối IMAP, lấy `limit` email MỚI NHẤT của thư mục.

    CHỦ Ý không dùng cờ UNSEEN như script cũ: HA quét định kỳ, nếu bạn
    mở mail trên điện thoại trước thì mail đó thành SEEN và sẽ bị bỏ
    sót. Thay vào đó lấy N mail gần nhất rồi khử trùng theo Message-ID
    ở coordinator. Cũng KHÔNG đánh dấu đã đọc / KHÔNG xóa mail.
    """
    conn = imaplib.IMAP4_SSL(host, port)
    try:
        conn.login(username, password)
        # readonly=True: tuyệt đối không làm thay đổi trạng thái hộp thư
        conn.select(folder, readonly=True)

        typ, data = conn.search(None, "ALL")
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
