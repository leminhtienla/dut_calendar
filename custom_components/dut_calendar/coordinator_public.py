"""Coordinator: tải trang lịch tuần định kỳ, lọc từ khóa, cảnh báo."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_KEYWORDS,
    CONF_NOTIFY_SERVICE,
    CONF_SCAN_INTERVAL,
    CONF_UPDATE_MODE,
    CONF_WEEKS_AHEAD,
    DEFAULT_SCAN_INTERVAL_PUBLIC as DEFAULT_SCAN_INTERVAL,
    DEFAULT_UPDATE_MODE,
    DEFAULT_WEEKS_AHEAD,
    DOMAIN,
    EVENT_MATCH_FOUND,
    LICHTUAN_BASE_URL,
    MAX_STORED_HASHES_PUBLIC as MAX_STORED_HASHES,
    SMART_MODE_WEEKDAY_THRESHOLD,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
    UPDATE_MODE_SMART,
)
from .parser_public import (
    build_week_url,
    filter_by_keywords,
    next_year_label,
    parse_current_week_info,
    parse_keyword_groups,
    parse_schedule,
)

_LOGGER = logging.getLogger(__name__)


class LichTuanDutCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Tải & xử lý dữ liệu lịch tuần DUT."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        interval_min = entry.options.get(
            CONF_SCAN_INTERVAL, entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_min),
        )
        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id)
        )
        self._seen_hashes: set[str] = set()
        self._loaded_storage = False

    @property
    def keyword_groups(self) -> list[dict[str, Any]]:
        """Danh sách nhóm từ khóa, mỗi nhóm gồm 1 nhãn + các biến thể/viết tắt."""
        raw = self.entry.options.get(
            CONF_KEYWORDS, self.entry.data.get(CONF_KEYWORDS, "")
        )
        if isinstance(raw, list):
            raw = "\n".join(raw)
        return parse_keyword_groups(str(raw))

    @property
    def keyword_labels(self) -> list[str]:
        """Danh sách nhãn nhóm từ khóa (dùng để tạo 1 sensor / nhóm)."""
        return [g["label"] for g in self.keyword_groups]

    @property
    def weeks_ahead(self) -> int:
        return int(
            self.entry.options.get(
                CONF_WEEKS_AHEAD, self.entry.data.get(CONF_WEEKS_AHEAD, DEFAULT_WEEKS_AHEAD)
            )
        )

    @property
    def update_mode(self) -> str:
        return self.entry.options.get(
            CONF_UPDATE_MODE, self.entry.data.get(CONF_UPDATE_MODE, DEFAULT_UPDATE_MODE)
        )

    @property
    def notify_service(self) -> str | None:
        val = self.entry.options.get(
            CONF_NOTIFY_SERVICE, self.entry.data.get(CONF_NOTIFY_SERVICE, "")
        )
        return val.strip() if val and val.strip() else None

    async def _async_load_storage(self) -> None:
        if self._loaded_storage:
            return
        data = await self._store.async_load()
        if data and isinstance(data.get("seen"), list):
            self._seen_hashes = set(data["seen"])
        self._loaded_storage = True

    async def _async_save_storage(self) -> None:
        # Giới hạn kích thước lưu trữ để không phình to vô hạn
        hashes = list(self._seen_hashes)[-MAX_STORED_HASHES:]
        self._seen_hashes = set(hashes)
        await self._store.async_save({"seen": hashes})

    async def _async_update_data(self) -> dict[str, Any]:
        await self._async_load_storage()

        keyword_groups = self.keyword_groups
        if not keyword_groups:
            return {"matches": [], "total_entries": 0, "new_matches": []}

        session = async_get_clientsession(self.hass)

        # --- Bước 1: lấy tuần/năm học HIỆN TẠI thật từ chính trang ---
        # (không tự tính công thức, vì năm học không cố định bắt đầu
        # 1/9 hay 1/8 — ranh giới do trường tự đặt và có thể lệch).
        try:
            async with session.get(LICHTUAN_BASE_URL, timeout=30) as resp:
                resp.raise_for_status()
                anchor_html = await resp.text()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Lỗi tải trang lịch tuần gốc: {err}") from err

        anchor = await self.hass.async_add_executor_job(parse_current_week_info, anchor_html)
        if anchor is None:
            raise UpdateFailed(
                "Không đọc được dropdown Tuần/Năm học trên trang — "
                "có thể trang đã đổi cấu trúc, cần cập nhật lại integration."
            )

        anchor_monday = date.fromisoformat(anchor["current_week"])
        anchor_year = anchor["current_year"]
        max_week_in_year = anchor["max_week_in_year"]

        all_entries: list[dict[str, Any]] = []

        # --- Xác định các tuần cần quét theo chế độ đã chọn ---
        if self.update_mode == UPDATE_MODE_SMART:
            # Chế độ gọn: luôn quét tuần hiện tại; chỉ quét thêm tuần kế
            # tiếp khi đã tới "cuối tuần" (mặc định từ Thứ 6), vì trường
            # thường công bố lịch tuần mới vào khoảng cuối tuần trước đó.
            offsets = [0]
            if date.today().weekday() >= SMART_MODE_WEEKDAY_THRESHOLD:
                offsets.append(1)
        else:
            # Chế độ toàn bộ: tuần hiện tại + đúng số tuần weeks_ahead đã cấu hình
            offsets = list(range(self.weeks_ahead + 1))

        for offset in offsets:
            monday = anchor_monday + timedelta(weeks=offset)
            # Nếu tuần mục tiêu vượt quá tuần cuối của năm học hiện tại,
            # tự động chuyển sang năm học kế tiếp (hiếm khi xảy ra, chỉ
            # khi weeks_ahead đẩy qua đúng dịp chuyển năm học).
            year_label = anchor_year
            if monday.isoformat() > max_week_in_year:
                year_label = next_year_label(anchor_year)

            if offset == 0:
                # Tuần hiện tại: dùng luôn HTML đã tải ở bước anchor,
                # khỏi tải lại lần 2 cho cùng 1 trang.
                html = anchor_html
            else:
                url = build_week_url(monday, year_label)
                try:
                    async with session.get(url, timeout=30) as resp:
                        resp.raise_for_status()
                        html = await resp.text()
                except Exception as err:  # noqa: BLE001
                    raise UpdateFailed(f"Lỗi tải lịch tuần ({url}): {err}") from err

            week_label = (
                f"{monday.strftime('%d/%m/%Y')} - {(monday + timedelta(days=6)).strftime('%d/%m/%Y')}"
            )
            entries = await self.hass.async_add_executor_job(parse_schedule, html, week_label)
            all_entries.extend(entries)

        matches = await self.hass.async_add_executor_job(
            filter_by_keywords, all_entries, keyword_groups
        )

        new_matches = [m for m in matches if m["id"] not in self._seen_hashes]

        if new_matches:
            for m in new_matches:
                self._seen_hashes.add(m["id"])
                self.hass.bus.async_fire(EVENT_MATCH_FOUND, m)
            await self._async_save_storage()
            await self._async_notify(new_matches)

        return {
            "matches": matches,
            "total_entries": len(all_entries),
            "new_matches": new_matches,
        }

    async def _async_notify(self, new_matches: list[dict[str, Any]]) -> None:
        """Gửi cảnh báo cho các mục mới khớp từ khóa."""
        title = f"Lịch tuần DUT: {len(new_matches)} mục mới khớp từ khóa"
        lines = []
        for m in new_matches[:10]:
            kw = ", ".join(m["matched_keywords"])
            variants = ", ".join(m.get("matched_variants", []))
            tag = "[Phụ lục] " if m.get("phu_luc") else ""
            lines.append(
                f"• {tag}{m['day']} {m['date']} {m['time']} — {m['content']} "
                f"(từ khóa: {kw} [{variants}], tại: {m['location']})"
            )
        if len(new_matches) > 10:
            lines.append(f"... và {len(new_matches) - 10} mục khác.")
        message = "\n".join(lines)

        # Luôn tạo persistent_notification trong HA
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{self.entry.entry_id}",
            },
            blocking=False,
        )

        # Nếu người dùng đã cấu hình service notify riêng (vd notify.mobile_app_xxx)
        service = self.notify_service
        if service and "." in service:
            domain, _, service_name = service.partition(".")
            try:
                await self.hass.services.async_call(
                    domain,
                    service_name,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Không thể gọi notify service '%s'", service)
