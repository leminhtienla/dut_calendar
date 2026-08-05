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
    CONF_KEYWORDS,
    CONF_MAIL_FOLDER,
    CONF_MAIL_HOST,
    CONF_MAIL_LIMIT,
    CONF_MAIL_PORT,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_MAIL_FOLDER,
    DEFAULT_MAIL_HOST,
    DEFAULT_MAIL_LIMIT,
    DEFAULT_MAIL_PORT,
    DEFAULT_SCAN_INTERVAL_MAIL,
    DOMAIN,
    EVENT_MAIL_MATCH,
    MAIL_HISTORY_RETENTION_DAYS,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
)
from .mail_client import fetch_recent_mails, filter_mails_by_keywords, mail_stable_id
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
    def _current_keywords_signature(self) -> str:
        raw = str(self._opt(CONF_KEYWORDS, ""))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    # ---------------- lưu trữ ----------------
    async def _async_load_storage(self) -> None:
        if self._loaded_storage:
            return
        data = await self._store.async_load()
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

        try:
            mails = await self.hass.async_add_executor_job(
                fetch_recent_mails,
                str(self._opt(CONF_MAIL_HOST, DEFAULT_MAIL_HOST)),
                int(self._opt(CONF_MAIL_PORT, DEFAULT_MAIL_PORT)),
                str(self._opt(CONF_USERNAME, "")),
                str(self._opt(CONF_PASSWORD, "")),
                str(self._opt(CONF_MAIL_FOLDER, DEFAULT_MAIL_FOLDER)),
                int(self._opt(CONF_MAIL_LIMIT, DEFAULT_MAIL_LIMIT)),
            )
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Lỗi đọc hộp thư: {err}") from err

        matches = await self.hass.async_add_executor_job(
            filter_mails_by_keywords, mails, groups
        )

        new_matches: list[dict[str, Any]] = []
        for m in matches:
            key = mail_stable_id(m)
            item = {
                "id": key,
                "sender": m.get("sender"),
                "subject": m.get("subject"),
                "received": m["received"].isoformat() if m.get("received") else None,
                "matched_keywords": m.get("matched_keywords"),
                "matched_variants": m.get("matched_variants"),
            }
            if key not in self._history:
                new_matches.append(item)
            self._history[key] = item

        if new_matches:
            for m in new_matches:
                self.hass.bus.async_fire(EVENT_MAIL_MATCH, m)
            await self._async_notify(new_matches)

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
