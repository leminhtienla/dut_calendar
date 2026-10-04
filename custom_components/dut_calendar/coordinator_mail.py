"""Coordinator: đọc hộp thư IMAP định kỳ, lọc từ khóa, cảnh báo mail mới."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AI_ENABLED,
    CONF_AI_ENTITY_ID,
    CONF_KEYWORDS,
    CONF_MAIL_EXCLUDE_SUBJECTS,
    CONF_MAIL_FOLDER,
    CONF_MAIL_HOST,
    CONF_MAIL_LIMIT,
    CONF_MAIL_PORT,
    CONF_MAIL_UNSEEN_ONLY,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_AI_ENABLED,
    DEFAULT_AI_ENTITY_ID,
    DEFAULT_MAIL_EXCLUDE_SUBJECTS,
    DEFAULT_MAIL_FOLDER,
    DEFAULT_MAIL_HOST,
    DEFAULT_MAIL_LIMIT,
    DEFAULT_MAIL_PORT,
    DEFAULT_MAIL_UNSEEN_ONLY,
    DEFAULT_SCAN_INTERVAL_MAIL,
    DOMAIN,
    EVENT_MAIL_MATCH,
    MAIL_HISTORY_RETENTION_DAYS,
    MAIL_PARSER_REVISION,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
)
from .mail_client import (
    fetch_recent_mails,
    filter_mails_by_keywords,
    build_ai_prompt,
    exclude_mails_by_subject,
    extract_original_sender,
    mail_stable_id,
    normalize_subject,
    parse_ai_response,
    parse_date_ranges,
    parse_deadlines,
    parse_exclude_subjects,
    parse_milestones,
    parse_meeting_info,
)
from .parser_public import parse_keyword_groups

_LOGGER = logging.getLogger(__name__)

# Giới hạn gọi AI — AI chậm/treo không được kéo theo cả setup/lần quét.
# Mỗi lần gọi tối đa AI_TIMEOUT_SECONDS; mỗi lần quét tối đa
# AI_MAX_CALLS_PER_REFRESH mail (phần còn lại để dành lần quét sau, vì
# mail chưa hỏi AI sẽ tự được thử lại).
AI_TIMEOUT_SECONDS = 25
AI_MAX_CALLS_PER_REFRESH = 3
# Còn mail chờ AI sau 1 lượt quét -> tự quét bù sau QUET_BU_SAU_GIAY giây
# (không đợi hết chu kỳ quét thường), tối đa QUET_BU_TOI_DA lần liên tiếp
# để không lặp mãi nếu AI cứ lỗi.
QUET_BU_SAU_GIAY = 60
QUET_BU_TOI_DA = 5


def _phan_tich_luat(body_text: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Tách thông tin từ thân mail bằng QUY TẮC (không dùng AI).

    Trả về `(info, han_list, date_ranges)`:
    - `info`: giờ họp / sự kiện cả ngày / địa điểm (parse_meeting_info)
    - `han_list`: các mốc hạn (mốc dạng "Nhãn: ngày" + hạn trong câu văn),
      đã khử trùng theo ngày
    - `date_ranges`: các khoảng "từ ngày X - Y" dạng liệt kê
    """
    info = parse_meeting_info(body_text)
    # Mail không có dòng "Thời gian:" (mời phản biện, nộp hồ sơ...)
    # thường chỉ nêu "trước ngày X" -> lấy làm mốc hạn.
    # Mốc dạng danh sách "Nhãn: ngày" (mail hội thảo) + hạn nêu
    # trong câu văn "trước ngày X" (mail mời phản biện).
    han_list = parse_milestones(body_text) + parse_deadlines(body_text)
    # Khử trùng theo ngày, ưu tiên nhãn ngắn gọn của danh sách
    da_co: set = set()
    han_gom = []
    for h in han_list:
        if h["date"] in da_co:
            continue
        da_co.add(h["date"])
        han_gom.append(h)
    # Khoảng "từ ngày X - Y" KHÔNG cần nhãn "Thời gian:" (mail liệt kê
    # nhiều đợt, vd sinh hoạt lớp chủ nhiệm) -> mỗi khoảng thành 1 sự
    # kiện CẢ NGÀY riêng.
    return info, han_gom, parse_date_ranges(body_text)


class DutMailCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Quét hộp thư, lọc theo nhóm từ khóa giống hệt cơ chế lịch tuần."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_mail",
            update_interval=timedelta(minutes=self.scan_interval_minutes),
        )
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id)
        )
        self._history: dict[str, dict[str, Any]] = {}
        self._keywords_signature: str | None = None
        self._loaded_storage = False
        # Lần quét ĐẦU TIÊN (chưa có lịch sử) sẽ nạp nền, KHÔNG thông
        # báo — nếu không sẽ bắn hàng loạt cảnh báo cho mail cũ ngay
        # khi vừa cài đặt.
        self._first_run = True
        # Bộ nhớ "mail đã xử lý xong" theo UID IMAP (lưu bền .storage —
        # CHỈ số UID, không lưu tiêu đề/nội dung) để mỗi lượt quét, kể cả
        # sau khi khởi động lại HA, chỉ tải mail MỚI thay vì cả cửa sổ.
        self._seen_uids: set[int] = set()
        self._uidvalidity: int | None = None
        self._scan_signature: str | None = None
        # Quét bù khi còn mail chờ AI
        self._cancel_followup = None
        self._so_lan_quet_bu = 0

    # ---------------- cấu hình ----------------
    def _opt(self, key: str, default: Any) -> Any:
        return self.entry.options.get(key, self.entry.data.get(key, default))

    @property
    def scan_interval_minutes(self) -> int:
        return int(
            self.entry.options.get(
                CONF_SCAN_INTERVAL,
                self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_MAIL),
            )
        )

    @property
    def keyword_groups(self) -> list[dict[str, Any]]:
        return parse_keyword_groups(str(self._opt(CONF_KEYWORDS, "")))

    @property
    def keyword_labels(self) -> list[str]:
        return [g["label"] for g in self.keyword_groups]

    @property
    def notify_service(self) -> str | None:
        v = self._opt(CONF_NOTIFY_SERVICE, "")
        return v.strip() if v and v.strip() else None

    @property
    def ai_enabled(self) -> bool:
        return bool(self._opt(CONF_AI_ENABLED, DEFAULT_AI_ENABLED))

    @property
    def ai_entity_id(self) -> str | None:
        v = self._opt(CONF_AI_ENTITY_ID, DEFAULT_AI_ENTITY_ID)
        return v.strip() if v and v.strip() else None

    @property
    def exclude_subjects(self) -> list[str]:
        raw = str(self._opt(CONF_MAIL_EXCLUDE_SUBJECTS, DEFAULT_MAIL_EXCLUDE_SUBJECTS))
        return parse_exclude_subjects(raw)

    @property
    def _current_keywords_signature(self) -> str:
        raw = str(self._opt(CONF_KEYWORDS, ""))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @property
    def _scan_signature_now(self) -> str:
        """Chữ ký của mọi thứ ảnh hưởng tới VIỆC MAIL NÀO ĐƯỢC COI LÀ
        "đã xử lý xong". Đổi bất kỳ thứ nào dưới đây thì bộ nhớ UID mất
        giá trị: mail trước đó bị loại/không khớp/chưa hỏi AI có thể cần
        xử lý khác đi, nên phải tải lại cửa sổ mail một lần.
        """
        thanh_phan = [
            str(self._opt(CONF_KEYWORDS, "")),
            "\n".join(self.exclude_subjects),
            f"ai={int(self.ai_enabled and bool(self.ai_entity_id))}",
            f"unseen={int(bool(self._opt(CONF_MAIL_UNSEEN_ONLY, DEFAULT_MAIL_UNSEEN_ONLY)))}",
            "{}|{}|{}".format(
                self._opt(CONF_MAIL_HOST, DEFAULT_MAIL_HOST),
                self._opt(CONF_USERNAME, ""),
                self._opt(CONF_MAIL_FOLDER, DEFAULT_MAIL_FOLDER),
            ),
            f"rev={MAIL_PARSER_REVISION}",
        ]
        return hashlib.sha1("\x1f".join(thanh_phan).encode("utf-8")).hexdigest()

    # ---------------- lưu trữ ----------------
    async def _async_load_storage(self) -> None:
        if self._loaded_storage:
            return
        data = await self._store.async_load()
        self._first_run = not (data and isinstance(data.get("mail_history"), dict))
        if data and isinstance(data.get("mail_history"), dict):
            self._history = data["mail_history"]
        if data and isinstance(data.get("mail_keywords_signature"), str):
            self._keywords_signature = data["mail_keywords_signature"]
        if data and isinstance(data.get("mail_seen_uids"), list):
            self._seen_uids = {u for u in data["mail_seen_uids"] if isinstance(u, int)}
        if data and isinstance(data.get("mail_uidvalidity"), int):
            self._uidvalidity = data["mail_uidvalidity"]
        if data and isinstance(data.get("mail_scan_signature"), str):
            self._scan_signature = data["mail_scan_signature"]
        self._loaded_storage = True

    async def _async_save_storage(self) -> None:
        await self._store.async_save(
            {
                "mail_history": self._history,
                "mail_keywords_signature": self._keywords_signature,
                "mail_seen_uids": sorted(self._seen_uids),
                "mail_uidvalidity": self._uidvalidity,
                "mail_scan_signature": self._scan_signature,
            }
        )

    def _prune_history(self) -> None:
        """Bỏ mail cũ hơn MAIL_HISTORY_RETENTION_DAYS ngày."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAIL_HISTORY_RETENTION_DAYS)
        kept: dict[str, dict[str, Any]] = {}
        for key, m in self._history.items():
            raw = m.get("received")
            if not raw:
                kept[key] = m  # không rõ ngày -> giữ, an toàn hơn xóa nhầm
                continue
            try:
                dt = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                kept[key] = m
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                kept[key] = m
        self._history = kept

    async def _async_ask_ai(
        self, subject: str, body: str
    ) -> tuple[bool, dict[str, Any] | None]:
        """Gọi AI conversation agent đã cấu hình để tìm thông tin mà
        rule-based KHÔNG tách được. Không bao giờ raise ra ngoài.

        Trả về `(da_tra_loi, ket_qua)`:
        - `da_tra_loi=True`: AI thật sự đã phản hồi (kể cả khi không tìm
          thấy gì, `ket_qua=None`) -> coordinator ghi nhớ đã hỏi, KHÔNG
          gửi lại mail này cho AI ở các lần quét sau.
        - `da_tra_loi=False`: lỗi/timeout/agent không phản hồi -> không
          ghi nhớ, lần quét sau được thử lại.

        CÓ TIMEOUT (`AI_TIMEOUT_SECONDS`): AI chậm/treo không được kéo
        theo cả setup entry (từng gây "Global task timeout: Bootstrap
        stage 2 timeout" khi agent Gemini phản hồi quá lâu lúc khởi động).

        CHỈ gửi tiêu đề + phần thân mail MỚI NHẤT (đã cắt trích dẫn cũ),
        không gửi toàn văn, không lưu lại prompt/kết quả thô vào .storage.
        """
        entity_id = self.ai_entity_id
        if not entity_id:
            return False, None
        try:
            prompt = build_ai_prompt(subject, body)
            async with asyncio.timeout(AI_TIMEOUT_SECONDS):
                resp = await self.hass.services.async_call(
                    "conversation",
                    "process",
                    {"text": prompt, "agent_id": entity_id, "language": "vi"},
                    blocking=True,
                    return_response=True,
                )
            speech = (
                resp.get("response", {})
                .get("speech", {})
                .get("plain", {})
                .get("speech", "")
            )
            if not speech:
                return True, None
            parsed = parse_ai_response(speech)
            if not any(
                parsed.get(k) for k in ("start", "all_day_start", "deadlines", "date_ranges")
            ):
                return True, None
            return True, parsed
        except TimeoutError:
            _LOGGER.warning(
                "AI (%s) không phản hồi trong %ds cho mail '%s', bỏ qua, sẽ thử lại lần quét sau",
                entity_id,
                AI_TIMEOUT_SECONDS,
                subject,
            )
            return False, None
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Không hỏi được AI (%s) cho mail '%s': %s", entity_id, subject, err)
            return False, None

    # ---------------- cập nhật ----------------
    async def _async_update_data(self) -> dict[str, Any]:
        t_bat_dau = time.monotonic()
        await self._async_load_storage()

        # Đổi từ khóa -> xóa lịch sử, quét lại (giống lịch tuần), tránh
        # còn sót mail chỉ khớp theo từ khóa CŨ.
        sig = self._current_keywords_signature
        if self._keywords_signature is not None and self._keywords_signature != sig:
            _LOGGER.info("Từ khóa mail đã đổi, xóa lịch sử cũ và quét lại")
            self._history = {}
        self._keywords_signature = sig

        groups = self.keyword_groups
        if not groups:
            return {"matches": [], "total_mails": 0, "new_matches": []}

        # Cấu hình ảnh hưởng tới việc "mail nào đã xử lý xong" đổi (từ
        # khóa, loại trừ, AI bật/tắt, hộp thư, phiên bản parser) -> bộ
        # nhớ UID hết giá trị, tải lại cửa sổ mail MỘT lần. Lịch sử đã
        # trích (kể cả kết quả AI) được giữ nguyên, không hỏi lại AI.
        sig_quet = self._scan_signature_now
        if self._scan_signature != sig_quet:
            if self._seen_uids:
                _LOGGER.info(
                    "dut_mail: cấu hình quét đã đổi, tải lại cửa sổ mail một lần"
                )
            self._seen_uids = set()
            self._uidvalidity = None
        self._scan_signature = sig_quet

        # Dọn NGAY các mail đã lỡ lưu vào lịch sử TỪ TRƯỚC khi khớp
        # cụm loại trừ hiện tại — nếu không dọn, mail cũ vẫn hiện mãi
        # (tối đa MAIL_HISTORY_RETENTION_DAYS ngày) dù exclude đã đúng,
        # vì exclude chỉ chặn mail MỚI, không hồi tố xóa lịch sử cũ.
        exclude_list = self.exclude_subjects
        if exclude_list and self._history:
            try:
                kept = await self.hass.async_add_executor_job(
                    exclude_mails_by_subject, list(self._history.values()), exclude_list
                )
                kept_ids = {it.get("id") for it in kept}
                so_luong_xoa = len(self._history) - len(kept_ids)
                if so_luong_xoa > 0:
                    self._history = {
                        k: v for k, v in self._history.items() if k in kept_ids
                    }
                    _LOGGER.info(
                        "dut_mail: đã dọn %d mail cũ trong lịch sử khớp cụm loại trừ %s",
                        so_luong_xoa,
                        exclude_list,
                    )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Lỗi khi dọn lịch sử theo cụm loại trừ: %s", err)

        uidvalidity_cu = self._uidvalidity
        t_tai = time.monotonic()
        try:
            ket_qua_tai = await self.hass.async_add_executor_job(
                fetch_recent_mails,
                str(self._opt(CONF_MAIL_HOST, DEFAULT_MAIL_HOST)),
                int(self._opt(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)),
                str(self._opt(CONF_USERNAME, "")),
                str(self._opt(CONF_PASSWORD, "")),
                str(self._opt(CONF_MAIL_FOLDER, DEFAULT_MAIL_FOLDER)),
                int(self._opt(CONF_MAIL_LIMIT, DEFAULT_MAIL_LIMIT)),
                bool(self._opt(CONF_MAIL_UNSEEN_ONLY, DEFAULT_MAIL_UNSEEN_ONLY)),
                sorted(self._seen_uids),
                self._uidvalidity,
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Lỗi đọc hộp thư: {err}") from err
        t_tai = time.monotonic() - t_tai

        mails = ket_qua_tai["mails"]  # CHỈ mail mới tải về
        window_uids = set(ket_qua_tai["window_uids"])
        so_bo_qua = ket_qua_tai["so_bo_qua"]
        self._uidvalidity = ket_qua_tai["uidvalidity"]
        if self._uidvalidity != uidvalidity_cu:
            # Server đổi UIDVALIDITY -> UID đã nhớ vô nghĩa (fetch đã bỏ qua).
            self._seen_uids = set()

        matches = mails
        try:
            matches = await self.hass.async_add_executor_job(
                exclude_mails_by_subject, mails, exclude_list
            )
        except Exception as err:  # noqa: BLE001
            # Lỗi loại trừ KHÔNG được làm gãy cả lần quét mail — coi như
            # bước loại trừ thất bại, dùng nguyên danh sách chưa lọc,
            # đúng nguyên tắc "thà trống còn hơn sai" áp cho chính nó.
            _LOGGER.warning("Lỗi khi loại trừ mail theo tiêu đề, bỏ qua bước này: %s", err)
            matches = mails
        # Log rõ ràng để kiểm tra: cấu hình đang dùng, số mail trước/sau.
        _LOGGER.info(
            "dut_mail loại trừ theo tiêu đề: cụm=%s | mới tải=%d | sau=%d | loại=%d",
            exclude_list,
            len(mails),
            len(matches),
            len(mails) - len(matches),
        )

        try:
            matches = await self.hass.async_add_executor_job(
                filter_mails_by_keywords, matches, groups
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Lỗi lọc từ khóa mail: {err}") from err

        # ---- Bước 1: tách bằng QUY TẮC cho từng mail khớp (rẻ, không ----
        # ---- gửi nội dung mail ra ngoài). Chỉ lưu phần đã tách — KHÔNG ----
        # ---- lưu toàn văn nội dung mail vào .storage.                  ----
        t_luat = time.monotonic()
        cong_viec: list[dict[str, Any]] = []
        for m in matches:
            key = mail_stable_id(m)
            # Mail ĐÃ được AI trả lời ở lần quét trước (kể cả trả lời
            # "không tìm thấy gì") -> giữ nguyên kết quả cũ, KHÔNG gửi
            # lại nội dung mail cho AI (lãng phí + đi ngược nguyên tắc
            # hạn chế đưa nội dung mail ra ngoài).
            truoc = self._history.get(key)
            if truoc is not None and (truoc.get("ai_tried") or truoc.get("ai_used")):
                continue
            info, han_list, date_ranges = _phan_tich_luat(m.get("body", ""))
            rule_trong = not (
                info.get("start")
                or info.get("all_day_start")
                or han_list
                or date_ranges
            )
            cong_viec.append(
                {
                    "m": m,
                    "key": key,
                    "info": info,
                    "han_list": han_list,
                    "date_ranges": date_ranges,
                    "rule_trong": rule_trong,
                }
            )
        t_luat = time.monotonic() - t_luat

        # ---- Bước 2: mail mà luật KHÔNG tách được gì -> nhờ AI, các lần ----
        # ---- gọi chạy SONG SONG. Chỉ khi HA đã khởi động xong (lúc đang ----
        # ---- bootstrap, gọi AI qua mạng ngoài có thể làm gãy cả setup), ----
        # ---- tối đa AI_MAX_CALLS_PER_REFRESH mail mỗi lượt.              ----
        co_the_hoi_ai = self.ai_enabled and bool(self.ai_entity_id)
        ung_vien_ai = [cv for cv in cong_viec if cv["rule_trong"] and co_the_hoi_ai]
        se_hoi_ai = (
            ung_vien_ai[:AI_MAX_CALLS_PER_REFRESH] if self.hass.is_running else []
        )
        ket_qua_ai: dict[str, tuple[bool, dict[str, Any] | None]] = {}
        t_ai = time.monotonic()
        if se_hoi_ai:
            tra_loi = await asyncio.gather(
                *(
                    self._async_ask_ai(cv["m"].get("subject", ""), cv["m"].get("body", ""))
                    for cv in se_hoi_ai
                )
            )
            for cv, kq in zip(se_hoi_ai, tra_loi):
                ket_qua_ai[cv["key"]] = kq
        t_ai = time.monotonic() - t_ai

        # ---- Bước 3: dựng kết quả từng mail ----
        new_matches: list[dict[str, Any]] = []
        cho_uids: set[int] = set()  # mail còn dở việc AI -> chưa coi là xong
        for cv in cong_viec:
            m, key = cv["m"], cv["key"]
            info, han_list, date_ranges = cv["info"], cv["han_list"], cv["date_ranges"]
            ai_used = False
            ai_nhan_phan_loai = None
            ai_da_tra_loi, ai_result = ket_qua_ai.get(key, (False, None))
            if ai_result:
                ai_used = True
                if ai_result.get("start"):
                    info["start"] = ai_result["start"]
                    info["location"] = ai_result.get("location") or info.get("location")
                elif ai_result.get("all_day_start"):
                    info["all_day_start"] = ai_result["all_day_start"]
                    info["all_day_end"] = ai_result["all_day_end"]
                    info["location"] = ai_result.get("location") or info.get("location")
                han_list = ai_result.get("deadlines") or []
                date_ranges = ai_result.get("date_ranges") or []
                ai_nhan_phan_loai = ai_result.get("nhan_phan_loai")
            if cv["rule_trong"] and co_the_hoi_ai and not ai_da_tra_loi:
                uid = m.get("uid")
                if uid is not None:
                    cho_uids.add(uid)
            item = {
                "id": key,
                "sender": m.get("sender"),
                # Mail forward: header From là người CHUYỂN TIẾP, người
                # gửi thật nằm trong phần trích dẫn -> lấy ra để hiển thị.
                "original_sender": extract_original_sender(m.get("body", "")),
                "subject": m.get("subject"),
                "subject_key": normalize_subject(m.get("subject", "")),
                "received": m["received"].isoformat() if m.get("received") else None,
                "matched_keywords": m.get("matched_keywords"),
                "matched_variants": m.get("matched_variants"),
                "meeting_start": info["start"].isoformat() if info.get("start") else None,
                "meeting_all_day_start": (
                    info["all_day_start"].isoformat() if info.get("all_day_start") else None
                ),
                "meeting_all_day_end": (
                    info["all_day_end"].isoformat() if info.get("all_day_end") else None
                ),
                "meeting_location": info.get("location"),
                "thoi_gian_raw": info.get("thoi_gian_raw"),
                "thanh_phan_raw": info.get("thanh_phan_raw"),
                "deadlines": [
                    {
                        "date": h["date"].isoformat(),
                        "gio": h.get("gio"),
                        "context": h["context"],
                    }
                    for h in han_list
                ],
                "date_ranges": [
                    {
                        "start": r["start"].isoformat(),
                        "end": r["end"].isoformat(),
                        "context": r.get("context") or "",
                    }
                    for r in date_ranges
                ],
                "ai_used": ai_used,
                "ai_nhan_phan_loai": ai_nhan_phan_loai,
                # True = AI đã phản hồi cho mail này (dù rỗng) -> lần quét
                # sau bỏ qua, không hỏi lại.
                "ai_tried": ai_da_tra_loi,
            }
            if key not in self._history:
                new_matches.append(item)
            self._history[key] = item

        if new_matches and self._first_run:
            _LOGGER.info(
                "Lần quét đầu: nạp nền %d email khớp từ khóa, không gửi thông báo",
                len(new_matches),
            )
            new_matches = []

        if new_matches:
            for m in new_matches:
                self.hass.bus.async_fire(EVENT_MAIL_MATCH, m)
            await self._async_notify(new_matches)

        self._first_run = False

        # Cập nhật bộ nhớ UID: mail vừa tải xong (trừ mail còn dở việc AI,
        # để lượt sau tải lại và hỏi tiếp) + mail đã biết còn trong cửa
        # sổ. UID rơi khỏi cửa sổ thì bỏ, bộ nhớ không phình ra.
        da_xu_ly = {m["uid"] for m in mails if m.get("uid") is not None} - cho_uids
        self._seen_uids = (da_xu_ly | self._seen_uids) & window_uids

        self._prune_history()
        await self._async_save_storage()

        # Còn mail chờ AI -> quét bù sớm thay vì đợi hết chu kỳ thường.
        if cho_uids:
            if self.hass.is_running and self._so_lan_quet_bu < QUET_BU_TOI_DA:
                self._len_quet_bu()
        else:
            self._so_lan_quet_bu = 0

        _LOGGER.info(
            "dut_mail quét xong: tải %.1fs (mới=%d, bỏ qua=%d) | luật %.2fs | "
            "AI %.1fs (%d mail, còn chờ=%d) | tổng %.1fs",
            t_tai,
            len(mails),
            so_bo_qua,
            t_luat,
            t_ai,
            len(se_hoi_ai),
            len(cho_uids),
            time.monotonic() - t_bat_dau,
        )

        all_matches = sorted(
            self._history.values(), key=lambda m: m.get("received") or "", reverse=True
        )
        return {
            "matches": all_matches,
            "total_mails": len(window_uids),
            "new_matches": new_matches,
        }

    # ---------------- quét bù / quét lại ----------------
    def _len_quet_bu(self) -> None:
        """Hẹn 1 lượt quét bù sau QUET_BU_SAU_GIAY giây."""
        self.huy_quet_bu()
        self._so_lan_quet_bu += 1
        self._cancel_followup = async_call_later(
            self.hass, QUET_BU_SAU_GIAY, self._async_quet_bu
        )

    async def _async_quet_bu(self, _now: Any) -> None:
        self._cancel_followup = None
        await self.async_request_refresh()

    def huy_quet_bu(self) -> None:
        """Hủy lượt quét bù đang chờ (gọi khi gỡ entry)."""
        if self._cancel_followup is not None:
            self._cancel_followup()
            self._cancel_followup = None

    async def async_fresh_load(self) -> None:
        """Quét lại TOÀN BỘ mail từ đầu (nút "Quét lại toàn bộ mail").

        MỨC SẠCH: xóa lịch sử, bộ nhớ UID VÀ cả kết quả AI đã có — mail
        nào luật không tách được sẽ bị hỏi lại AI (vẫn theo hạn mức
        mỗi lượt, phần còn lại tự quét bù). Dùng khi đổi agent AI/prompt
        hoặc muốn chắc chắn mọi thứ tính lại từ đầu. Mail cũ nạp nền,
        KHÔNG bắn thông báo.

        Chỉ xóa trong bộ nhớ; .storage được ghi lại sau khi quét thành
        công — nếu lần quét này lỗi mạng, dữ liệu cũ trên Calendar vẫn
        còn nguyên cho tới khi quét được.
        """
        _LOGGER.info("dut_mail: quét lại toàn bộ (xóa lịch sử, bộ nhớ UID, kết quả AI)")
        self.huy_quet_bu()
        await self._async_load_storage()
        self._history = {}
        self._seen_uids = set()
        self._uidvalidity = None
        self._so_lan_quet_bu = 0
        self._first_run = True
        await self.async_refresh()

    async def _async_notify(self, new_matches: list[dict[str, Any]]) -> None:
        service = self.notify_service
        if not service:
            return
        lines = [
            f"• [{', '.join(m['matched_keywords'])}] {m['subject']} — {m['sender']}"
            for m in new_matches[:10]
        ]
        if len(new_matches) > 10:
            lines.append(f"... và {len(new_matches) - 10} mail khác.")
        try:
            domain, name = service.split(".", 1)
            await self.hass.services.async_call(
                domain,
                name,
                {"title": f"Email mới khớp từ khóa ({len(new_matches)})", "message": "\n".join(lines)},
                blocking=False,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Không gửi được thông báo mail qua %s: %s", service, err)
