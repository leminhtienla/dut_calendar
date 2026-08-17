"""Coordinator: đọc hộp thư IMAP định kỳ, lọc từ khóa, cảnh báo mail mới."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
        self._loaded_storage = True

    async def _async_save_storage(self) -> None:
        await self._store.async_save(
            {
                "mail_history": self._history,
                "mail_keywords_signature": self._keywords_signature,
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

    async def _async_ask_ai(self, subject: str, body: str) -> dict[str, Any] | None:
        """Gọi AI conversation agent đã cấu hình để tìm thông tin mà
        rule-based KHÔNG tách được. Không bao giờ raise ra ngoài — lỗi
        gì cũng coi như AI không giúp được gì, giữ nguyên hành vi cũ.

        CHỈ gửi tiêu đề + phần thân mail MỚI NHẤT (đã cắt trích dẫn cũ),
        không gửi toàn văn, không lưu lại prompt/kết quả thô vào .storage.
        """
        entity_id = self.ai_entity_id
        if not entity_id:
            return None
        try:
            prompt = build_ai_prompt(subject, body)
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
                return None
            parsed = parse_ai_response(speech)
            if not any(
                parsed.get(k) for k in ("start", "all_day_start", "deadlines", "date_ranges")
            ):
                return None
            return parsed
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Không hỏi được AI (%s) cho mail '%s': %s", entity_id, subject, err)
            return None

    # ---------------- cập nhật ----------------
    async def _async_update_data(self) -> dict[str, Any]:
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

        try:
            mails = await self.hass.async_add_executor_job(
                fetch_recent_mails,
                str(self._opt(CONF_MAIL_HOST, DEFAULT_MAIL_HOST)),
                int(self._opt(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)),
                str(self._opt(CONF_USERNAME, "")),
                str(self._opt(CONF_PASSWORD, "")),
                str(self._opt(CONF_MAIL_FOLDER, DEFAULT_MAIL_FOLDER)),
                int(self._opt(CONF_MAIL_LIMIT, DEFAULT_MAIL_LIMIT)),
                bool(self._opt(CONF_MAIL_UNSEEN_ONLY, DEFAULT_MAIL_UNSEEN_ONLY)),
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Lỗi đọc hộp thư: {err}") from err

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
        # Nếu dòng này KHÔNG xuất hiện trong log -> code exclude chưa
        # thực sự chạy (chưa deploy/restart đúng bản); nếu xuất hiện mà
        # "loại: 0" trong khi lẽ ra phải loại -> đúng là lỗi logic thật,
        # cần xem tiếp phần "mail còn lại" để biết vì sao không khớp.
        _LOGGER.info(
            "dut_mail loại trừ theo tiêu đề: cụm=%s | trước=%d | sau=%d | loại=%d",
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

        new_matches: list[dict[str, Any]] = []
        for m in matches:
            key = mail_stable_id(m)
            # Tách thời gian/địa điểm cuộc họp bằng QUY TẮC trước (không
            # dùng AI, không gửi nội dung mail ra ngoài); chỉ khi rule
            # thất bại hoàn toàn mới nhờ AI (xem bên dưới). Chỉ lưu phần
            # đã tách — KHÔNG lưu toàn văn nội dung mail vào .storage.
            body_text = m.get("body", "")
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
            han_list = han_gom

            # Khoảng "từ ngày X - Y" KHÔNG cần nhãn "Thời gian:" (mail
            # liệt kê nhiều đợt, vd sinh hoạt lớp chủ nhiệm) -> mỗi
            # khoảng thành 1 sự kiện CẢ NGÀY riêng.
            date_ranges = parse_date_ranges(body_text)

            # Rule-based KHÔNG tách được gì cả (mail đã khớp từ khóa
            # nhưng không đúng khuôn nào) -> nhờ AI thử tìm giúp, CHỈ
            # khi tính năng bật và có cấu hình entity. AI không được ưu
            # tiên hơn rule; chỉ chạy khi rule đã thất bại hoàn toàn.
            ai_used = False
            rule_trong = not (
                info.get("start")
                or info.get("all_day_start")
                or han_list
                or date_ranges
            )
            if rule_trong and self.ai_enabled and self.ai_entity_id:
                ai_result = await self._async_ask_ai(m.get("subject", ""), body_text)
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

        self._prune_history()
        await self._async_save_storage()

        all_matches = sorted(
            self._history.values(), key=lambda m: m.get("received") or "", reverse=True
        )
        return {
            "matches": all_matches,
            "total_mails": len(mails),
            "new_matches": new_matches,
        }

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
