"""Coordinator: đăng nhập, tải lịch coi thi định kỳ, cảnh báo mục mới."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_exam import CBDutAuthError, CBDutClient
from .const import (
    CONF_EXAM_DURATION,
    CONF_EXTRA_LECTURER,
    CONF_HOC_KY,
    CONF_NOTIFY_SERVICE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TYPE,
    CONF_USERNAME,
    DEFAULT_EXAM_DURATION,
    DEFAULT_SCAN_INTERVAL_EXAM as DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    EVENT_GRADE_DEADLINE_CHANGED,
    EVENT_NEW_EXAM_DUTY,
    MAX_STORED_HASHES_EXAM as MAX_STORED_HASHES,
    STORAGE_KEY_TEMPLATE,
    STORAGE_VERSION,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
)
from .parser_exam import (
    exam_hash,
    filter_exam_duty_by_lecturer,
    parse_class_deadline,
    parse_class_list,
    parse_exam_datetime,
    parse_exam_duty,
    parse_grade_deadline,
)

_LOGGER = logging.getLogger(__name__)


class CBDutCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Tải & xử lý dữ liệu lịch coi thi từ cb.dut.udn.vn."""

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

        # Session HTTP riêng (cookie jar riêng), không dùng chung của HA,
        # để cookie đăng nhập cổng cb.dut.udn.vn không lẫn integration khác.
        self._session = aiohttp.ClientSession()
        username = entry.options.get(CONF_USERNAME, entry.data[CONF_USERNAME])
        password = entry.options.get(CONF_PASSWORD, entry.data[CONF_PASSWORD])
        self._client = CBDutClient(self._session, username, password)

        self._store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_TEMPLATE.format(entry_id=entry.entry_id)
        )
        self._seen_hashes: set[str] = set()
        self._known_deadlines: dict[str, dict[str, str | None]] = {}
        self._loaded_storage = False

    async def async_close(self) -> None:
        await self._session.close()

    @property
    def hoc_ky_list(self) -> list[str]:
        raw = self.entry.options.get(
            CONF_HOC_KY, self.entry.data.get(CONF_HOC_KY, "")
        )
        return [x.strip() for x in str(raw).split(",") if x.strip()]

    @property
    def exam_duration(self) -> int:
        return int(
            self.entry.options.get(
                CONF_EXAM_DURATION,
                self.entry.data.get(CONF_EXAM_DURATION, DEFAULT_EXAM_DURATION),
            )
        )

    @property
    def notify_service(self) -> str | None:
        val = self.entry.options.get(
            CONF_NOTIFY_SERVICE, self.entry.data.get(CONF_NOTIFY_SERVICE, "")
        )
        return val.strip() if val and val.strip() else None

    @property
    def is_coithi(self) -> bool:
        return self.entry.data.get(CONF_TYPE) == TYPE_COITHI

    @property
    def is_deadline_diem(self) -> bool:
        return self.entry.data.get(CONF_TYPE) == TYPE_DEADLINE_DIEM

    @property
    def extra_lecturer(self) -> str | None:
        """Tên giảng viên khác cần theo dõi thêm (ngoài tài khoản đang đăng nhập)."""
        val = self.entry.options.get(
            CONF_EXTRA_LECTURER, self.entry.data.get(CONF_EXTRA_LECTURER, "")
        )
        return val.strip() if val and val.strip() else None

    async def _async_load_storage(self) -> None:
        if self._loaded_storage:
            return
        data = await self._store.async_load()
        if data and isinstance(data.get("seen"), list):
            self._seen_hashes = set(data["seen"])
        if data and isinstance(data.get("deadlines"), dict):
            self._known_deadlines = data["deadlines"]
        self._loaded_storage = True

    async def _async_save_storage(self) -> None:
        hashes = list(self._seen_hashes)[-MAX_STORED_HASHES:]
        self._seen_hashes = set(hashes)
        await self._store.async_save(
            {"seen": hashes, "deadlines": self._known_deadlines}
        )

    async def _async_update_data(self) -> dict[str, Any]:
        await self._async_load_storage()

        hoc_ky_list = self.hoc_ky_list
        if not hoc_ky_list:
            return {"duties": [], "new_duties": []}

        all_duties: list[dict[str, Any]] = []
        for hoc_ky in hoc_ky_list:
            try:
                html = await self._client.fetch_exam_duty_html(hoc_ky)
            except CBDutAuthError as err:
                raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
            except Exception as err:  # noqa: BLE001
                raise UpdateFailed(f"Lỗi tải lịch coi thi (HK {hoc_ky}): {err}") from err

            duties = await self.hass.async_add_executor_job(
                parse_exam_duty, html, hoc_ky
            )
            for d in duties:
                d["extra_lecturer_match"] = False
            all_duties.extend(duties)

        # --- Theo dõi thêm 1 giảng viên khác (nếu bật) ---
        # Tải danh sách TOÀN BỘ (không giới hạn theo tài khoản đăng nhập)
        # rồi lọc cục bộ theo tên, gộp thêm vào all_duties.
        lecturer = self.extra_lecturer
        if self.is_coithi and lecturer:
            for hoc_ky in hoc_ky_list:
                try:
                    html_all = await self._client.fetch_exam_duty_all_html(hoc_ky)
                except CBDutAuthError as err:
                    raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "Không lấy được danh sách toàn bộ ca thi cho HK %s (giảng viên khác)",
                        hoc_ky,
                    )
                    continue

                all_that_week = await self.hass.async_add_executor_job(
                    parse_exam_duty, html_all, hoc_ky
                )
                matched = await self.hass.async_add_executor_job(
                    filter_exam_duty_by_lecturer, all_that_week, lecturer
                )
                for d in matched:
                    d["extra_lecturer_match"] = True
                all_duties.extend(matched)

        # Khử trùng theo id (vd giảng viên khác vốn đã là "Cán bộ 2" cùng
        # coi thi với tài khoản đang đăng nhập -> giữ lại bản ghi xuất
        # hiện TRƯỚC, tức bản của chính tài khoản đăng nhập).
        seen_ids: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for d in all_duties:
            _id = exam_hash(d)
            d["id"] = _id
            if _id in seen_ids:
                continue
            seen_ids.add(_id)
            deduped.append(d)
        all_duties = deduped

        # Tính start/end + id cho từng ca thi
        duration = self.exam_duration
        for d in all_duties:
            start, end = parse_exam_datetime(d["thoi_gian_raw"], duration)
            d["start"] = start
            d["end"] = end
            d["id"] = exam_hash(d)

        from datetime import datetime as _dt

        all_duties.sort(key=lambda d: d["start"] or _dt.min)

        new_duties = [d for d in all_duties if d["id"] not in self._seen_hashes]

        if self.is_coithi and new_duties:
            for d in new_duties:
                self._seen_hashes.add(d["id"])
                # CalendarEvent/datetime không tự serialize qua bus event, nên
                # bắn dữ liệu dạng chuỗi để tránh lỗi JSON serialize.
                event_data = {k: v for k, v in d.items() if k not in ("start", "end")}
                event_data["start"] = d["start"].isoformat() if d["start"] else None
                event_data["end"] = d["end"].isoformat() if d["end"] else None
                self.hass.bus.async_fire(EVENT_NEW_EXAM_DUTY, event_data)
            await self._async_save_storage()
            await self._async_notify(new_duties)

        # --- Hạn nhập điểm (chỉ với entry loại "dut_deadline_diem") ---
        # Có 2 loại hạn KHÁC NHAU:
        #  1. Hạn điểm CUỐI KỲ THI CHUNG — theo "ca thi" (tái dùng mã ca thi
        #     đã có từ danh sách coi thi), áp dụng chung cho cả ca thi.
        #  2. Hạn điểm GIỮA KỲ / THÀNH PHẦN — khác nhau theo TỪNG LỚP học
        #     phần cụ thể, phải tra riêng từng lớp qua danh sách lớp phụ trách.
        # CHỦ Ý: cả 2 API đều chỉ đọc phần header hạn nộp điểm, KHÔNG đụng
        # tới bảng điểm/tên/mã số sinh viên nằm trong cùng response.
        grade_deadlines: dict[str, dict[str, Any]] = {}
        changed_deadlines: list[dict[str, Any]] = []

        if self.is_deadline_diem:
            for hoc_ky in hoc_ky_list:
                hk_result: dict[str, Any] = {"ca_thi_chung": None, "theo_lop": {}}

                # 1. Hạn điểm cuối kỳ thi chung (theo ca thi)
                sample_ca = next(
                    (
                        d["ma_ca_thi"]
                        for d in all_duties
                        if d["hoc_ky_label"] == hoc_ky and d.get("ma_ca_thi")
                    ),
                    None,
                )
                if sample_ca:
                    try:
                        raw = await self._client.fetch_grade_deadline_html(sample_ca)
                        hk_result["ca_thi_chung"] = await self.hass.async_add_executor_job(
                            parse_grade_deadline, raw
                        )
                    except CBDutAuthError as err:
                        raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "Không lấy được hạn điểm cuối kỳ thi chung cho HK %s", hoc_ky
                        )

                # 2. Hạn điểm giữa kỳ/thành phần (theo từng lớp)
                try:
                    class_list_html = await self._client.fetch_class_list_html(hoc_ky)
                    classes = await self.hass.async_add_executor_job(
                        parse_class_list, class_list_html
                    )
                except CBDutAuthError as err:
                    raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                except Exception:  # noqa: BLE001
                    _LOGGER.warning("Không lấy được danh sách lớp cho HK %s", hoc_ky)
                    classes = []

                for cls in classes:
                    try:
                        raw = await self._client.fetch_class_deadline_html(cls["ma_lop"])
                    except CBDutAuthError as err:
                        raise UpdateFailed(f"Lỗi đăng nhập cb.dut.udn.vn: {err}") from err
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning("Không lấy được hạn điểm cho lớp %s", cls["ma_lop"])
                        continue

                    parsed = await self.hass.async_add_executor_job(parse_class_deadline, raw)
                    hk_result["theo_lop"][cls["ma_lop"]] = {
                        **parsed,
                        "ten_lop": cls["ten_lop"],
                        "ma_lop_display": cls["ma_lop_display"],
                    }

                grade_deadlines[hoc_ky] = hk_result

                if self._known_deadlines.get(hoc_ky) != hk_result:
                    self._known_deadlines[hoc_ky] = hk_result
                    changed_deadlines.append({"hoc_ky": hoc_ky, **hk_result})

            if changed_deadlines:
                for c in changed_deadlines:
                    self.hass.bus.async_fire(EVENT_GRADE_DEADLINE_CHANGED, c)
                await self._async_save_storage()
                await self._async_notify_deadline(changed_deadlines)

        return {
            "duties": all_duties,
            "new_duties": new_duties,
            "grade_deadlines": grade_deadlines,
        }

    async def _async_notify_deadline(self, changed: list[dict[str, Any]]) -> None:
        title = "Hạn nộp điểm cập nhật"
        lines = []
        for c in changed:
            lines.append(f"HK {c['hoc_ky']}:")
            ca_thi_chung = c.get("ca_thi_chung")
            if ca_thi_chung:
                lines.append(
                    f"  • Thi chung: nhập điểm {ca_thi_chung.get('ngay_bat_dau') or '?'} → "
                    f"{ca_thi_chung.get('ngay_ket_thuc') or '?'}, nộp bản điểm "
                    f"{ca_thi_chung.get('ngay_nop_ban_diem') or '?'}"
                )
            for ma_lop, info in c.get("theo_lop", {}).items():
                gk = info.get("ngay_giua_ky")
                tp = info.get("ngay_thanh_phan") or info.get("ngay_cuoi_ky")
                if gk or tp:
                    lines.append(
                        f"  • {info.get('ten_lop', ma_lop)}: giữa kỳ {gk or '?'}, "
                        f"thành phần/cuối kỳ {tp or '?'}"
                    )
        message = "\n".join(lines)

        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}_{self.entry.entry_id}_deadline",
            },
            blocking=False,
        )

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

    async def _async_notify(self, new_duties: list[dict[str, Any]]) -> None:
        title = f"Lịch coi thi: {len(new_duties)} ca thi mới"
        lines = []
        for d in new_duties[:10]:
            start = d["start"]
            time_str = start.strftime("%H:%M %d/%m/%Y") if start else d["thoi_gian_raw"]
            if d.get("extra_lecturer_match"):
                tag = f"[{d.get('can_bo_1') or d.get('can_bo_2')}] "
            else:
                tag = ""
            lines.append(
                f"• {tag}{d['mon_thi']} — {time_str}, phòng {d['phong']} "
                f"(cùng coi thi: {d['can_bo_2']})"
            )
        if len(new_duties) > 10:
            lines.append(f"... và {len(new_duties) - 10} ca khác.")
        message = "\n".join(lines)

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
