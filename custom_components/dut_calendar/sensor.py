"""Sensor cho DUT Calendar — nhánh theo loại coordinator (public/exam)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TYPE, DOMAIN, TYPE_COITHI, TYPE_DEADLINE_DIEM
from .coordinator_exam import CBDutCoordinator
from .coordinator_public import LichTuanDutCoordinator
from .parser_exam import build_deadline_events, parse_vn_date
from .parser_public import parse_event_datetime

MAX_ATTR_ENTRIES = 25
PERIODS = ("today", "tomorrow", "month")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    if isinstance(coordinator, LichTuanDutCoordinator):
        entities: list[SensorEntity] = [PublicTotalSensor(coordinator, entry)]
        for label in coordinator.keyword_labels:
            entities.append(PublicKeywordSensor(coordinator, entry, label))
        entities += [
            PublicCountSensor(coordinator, entry, period) for period in PERIODS
        ]
        async_add_entities(entities)
    elif isinstance(coordinator, CBDutCoordinator):
        entry_type = entry.data.get(CONF_TYPE)
        if entry_type == TYPE_COITHI:
            async_add_entities(
                [ExamDutySensor(coordinator, entry)]
                + [CoithiCountSensor(coordinator, entry, period) for period in PERIODS]
            )
        elif entry_type == TYPE_DEADLINE_DIEM:
            async_add_entities(
                [GradeDeadlineSensor(coordinator, entry)]
                + [DeadlineCountSensor(coordinator, entry, period) for period in PERIODS]
            )


# =====================================================================
# Nguồn 1: Lịch tuần công khai
# =====================================================================
def _device_info_public(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Lịch tuần",
        manufacturer="lichtuan.dut.udn.vn (không chính thức)",
        model="Cảnh báo từ khóa",
    )


def _simplify_public(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "day": m.get("day"),
            "date": m.get("date"),
            "time": m.get("time"),
            "content": m.get("content"),
            "location": m.get("location"),
            "host": m.get("host"),
            "matched_keywords": m.get("matched_keywords"),
            "week": m.get("week_label"),
            "phu_luc": m.get("phu_luc", False),
        }
        for m in matches[:MAX_ATTR_ENTRIES]
    ]


class PublicTotalSensor(CoordinatorEntity[LichTuanDutCoordinator], SensorEntity):
    """Sensor tổng hợp: tổng số mục đang khớp (mọi từ khóa gộp lại)."""

    _attr_has_entity_name = True
    _attr_name = "Cảnh báo lịch tuần (tổng)"
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: LichTuanDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_matches_total"
        self._attr_device_info = _device_info_public(entry)

    @property
    def native_value(self) -> int:
        data = self.coordinator.data or {}
        return len(data.get("matches", []))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        matches = data.get("matches", [])
        new_matches = data.get("new_matches", [])
        return {
            "keyword_groups": self.coordinator.keyword_groups,
            "total_entries_scanned": data.get("total_entries", 0),
            "matches_count": len(matches),
            "new_matches_last_update": len(new_matches),
            "matches": _simplify_public(matches),
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


class PublicKeywordSensor(CoordinatorEntity[LichTuanDutCoordinator], SensorEntity):
    """Sensor riêng cho 1 NHÓM từ khóa (nhãn + các biến thể/viết tắt)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-search"

    def __init__(
        self, coordinator: LichTuanDutCoordinator, entry: ConfigEntry, label: str
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._label = label
        self._attr_name = f"Cảnh báo: {label}"
        kw_hash = hashlib.sha1(label.strip().lower().encode("utf-8")).hexdigest()[:12]
        self._attr_unique_id = f"{entry.entry_id}_keyword_{kw_hash}"
        self._attr_device_info = _device_info_public(entry)

    @property
    def _keyword_matches(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        matches = data.get("matches", [])
        return [m for m in matches if self._label in m.get("matched_keywords", [])]

    @property
    def native_value(self) -> int:
        return len(self._keyword_matches)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        new_matches = [
            m
            for m in data.get("new_matches", [])
            if self._label in m.get("matched_keywords", [])
        ]
        matches = self._keyword_matches
        variants: list[str] = []
        for g in self.coordinator.keyword_groups:
            if g["label"] == self._label:
                variants = g["variants"]
                break
        return {
            "label": self._label,
            "variants": variants,
            "matches_count": len(matches),
            "new_matches_last_update": len(new_matches),
            "matches": _simplify_public(matches),
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


# =====================================================================
# Nguồn 2: Lịch coi thi & hạn nộp điểm
# =====================================================================
def _device_info_coithi(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Coi thi",
        manufacturer="cb.dut.udn.vn (không chính thức)",
        model="Cảnh báo lịch coi thi",
    )


def _device_info_deadline(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Hạn nộp điểm",
        manufacturer="cb.dut.udn.vn (không chính thức)",
        model="Cảnh báo hạn nộp điểm",
    )


class ExamDutySensor(CoordinatorEntity[CBDutCoordinator], SensorEntity):
    """State = số ca thi SẮP TỚI (chưa diễn ra) trong các học kỳ đang theo dõi."""

    _attr_has_entity_name = True
    _attr_name = "Lịch coi thi"
    _attr_icon = "mdi:clipboard-text-clock"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_exam_duty"
        self._attr_device_info = _device_info_coithi(entry)

    @property
    def _upcoming(self) -> list[dict[str, Any]]:
        data = self.coordinator.data or {}
        now = dt_util.now().replace(tzinfo=None)
        return [d for d in data.get("duties", []) if d.get("start") and d["start"] >= now]

    @property
    def native_value(self) -> int:
        return len(self._upcoming)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        new_duties = data.get("new_duties", [])
        simplified = [
            {
                "mon_thi": d.get("mon_thi"),
                "thoi_gian": d.get("thoi_gian_raw"),
                "phong": d.get("phong"),
                "can_bo_1": d.get("can_bo_1"),
                "can_bo_2": d.get("can_bo_2"),
                "hoc_ky": d.get("hoc_ky_label"),
                "giang_vien_khac": d.get("extra_lecturer_match", False),
            }
            for d in self._upcoming[:MAX_ATTR_ENTRIES]
        ]
        return {
            "hoc_ky_theo_doi": self.coordinator.hoc_ky_list,
            "giang_vien_khac_theo_doi": self.coordinator.extra_lecturer,
            "so_ca_sap_toi": len(self._upcoming),
            "so_ca_moi_lan_quet_gan_nhat": len(new_duties),
            "ca_thi": simplified,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


class GradeDeadlineSensor(CoordinatorEntity[CBDutCoordinator], SensorEntity):
    """State = mốc hạn nộp điểm gần nhất SẮP TỚI (mọi loại: thi chung,
    giữa kỳ, thành phần, đính chính — của mọi lớp/học kỳ đang theo dõi).
    KHÔNG chứa điểm/thông tin sinh viên.
    """

    _attr_has_entity_name = True
    _attr_name = "Hạn nộp điểm"
    _attr_icon = "mdi:calendar-alert"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_grade_deadline"
        self._attr_device_info = _device_info_deadline(entry)

    @property
    def _deadlines(self) -> dict[str, Any]:
        data = self.coordinator.data or {}
        return data.get("grade_deadlines", {})

    @property
    def native_value(self) -> date | None:
        today = dt_util.now().date()
        candidates: list[date] = []

        for hk_info in self._deadlines.values():
            ca_thi_chung = hk_info.get("ca_thi_chung") or {}
            for key in ("ngay_ket_thuc", "ngay_nop_ban_diem", "han_dinh_chinh"):
                d = parse_vn_date(ca_thi_chung.get(key))
                if d and d >= today:
                    candidates.append(d)

            for lop_info in hk_info.get("theo_lop", {}).values():
                for key in (
                    "ngay_giua_ky",
                    "ngay_thanh_phan",
                    "ngay_cuoi_ky",
                    "han_dinh_chinh_giua_ky",
                    "han_dinh_chinh_thanh_phan",
                ):
                    d = parse_vn_date(lop_info.get(key))
                    if d and d >= today:
                        candidates.append(d)

        return min(candidates) if candidates else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        result = {}
        for hoc_ky, hk_info in self._deadlines.items():
            theo_lop = {
                ma_lop: {
                    "ten_lop": info.get("ten_lop"),
                    "ngay_giua_ky": info.get("ngay_giua_ky"),
                    "ngay_thanh_phan": info.get("ngay_thanh_phan"),
                    "ngay_cuoi_ky": info.get("ngay_cuoi_ky"),
                    "han_dinh_chinh_giua_ky": info.get("han_dinh_chinh_giua_ky"),
                    "han_dinh_chinh_thanh_phan": info.get("han_dinh_chinh_thanh_phan"),
                }
                for ma_lop, info in hk_info.get("theo_lop", {}).items()
            }
            result[hoc_ky] = {
                "thi_chung": hk_info.get("ca_thi_chung"),
                "theo_lop": theo_lop,
            }
        return {
            "hoc_ky_theo_doi": self.coordinator.hoc_ky_list,
            "chi_tiet_theo_hoc_ky": result,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


# =====================================================================
# Sensor đếm số sự kiện: Hôm nay / Ngày mai / Tháng này
# (dùng chung cho cả 3 loại, mỗi loại override _event_dates())
# =====================================================================
_PERIOD_LABELS = {"today": "Hôm nay", "tomorrow": "Ngày mai", "month": "Tháng này"}
_PERIOD_ICONS = {
    "today": "mdi:calendar-today",
    "tomorrow": "mdi:calendar-arrow-right",
    "month": "mdi:calendar-month",
}


def _to_date(value: Any) -> date | None:
    """Chuẩn hóa date hoặc datetime về date thuần để so sánh."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value


class _CountSensorBase(CoordinatorEntity, SensorEntity):
    """Lớp cơ sở: đếm số sự kiện rơi vào hôm nay/ngày mai/tháng này."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: Any, entry: ConfigEntry, period: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._period = period
        self._attr_name = _PERIOD_LABELS[period]
        self._attr_icon = _PERIOD_ICONS[period]
        self._attr_unique_id = f"{entry.entry_id}_count_{period}"

    def _event_dates(self) -> list[date]:
        """Trả về danh sách ngày của mọi sự kiện đang có — subclass tự cài."""
        raise NotImplementedError

    @property
    def native_value(self) -> int:
        today = dt_util.now().date()
        dates = [d for d in self._event_dates() if d]

        if self._period == "today":
            return sum(1 for d in dates if d == today)
        if self._period == "tomorrow":
            return sum(1 for d in dates if d == today + timedelta(days=1))
        # "month"
        return sum(1 for d in dates if d.year == today.year and d.month == today.month)


class PublicCountSensor(_CountSensorBase):
    """Đếm số mục lịch tuần khớp từ khóa theo hôm nay/ngày mai/tháng này."""

    def __init__(
        self, coordinator: LichTuanDutCoordinator, entry: ConfigEntry, period: str
    ) -> None:
        super().__init__(coordinator, entry, period)
        self._attr_device_info = _device_info_public(entry)

    def _event_dates(self) -> list[date]:
        data = self.coordinator.data or {}
        dates: list[date] = []
        for m in data.get("matches", []):
            start, _end, _all_day = parse_event_datetime(m.get("date", ""), m.get("time", ""))
            d = _to_date(start)
            if d:
                dates.append(d)
        return dates


class CoithiCountSensor(_CountSensorBase):
    """Đếm số ca coi thi theo hôm nay/ngày mai/tháng này."""

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry, period: str) -> None:
        super().__init__(coordinator, entry, period)
        self._attr_device_info = _device_info_coithi(entry)

    def _event_dates(self) -> list[date]:
        data = self.coordinator.data or {}
        return [
            _to_date(d["start"])
            for d in data.get("duties", [])
            if d.get("start")
        ]


class DeadlineCountSensor(_CountSensorBase):
    """Đếm số mốc hạn nộp điểm theo hôm nay/ngày mai/tháng này."""

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry, period: str) -> None:
        super().__init__(coordinator, entry, period)
        self._attr_device_info = _device_info_deadline(entry)

    def _event_dates(self) -> list[date]:
        data = self.coordinator.data or {}
        events = build_deadline_events(data.get("grade_deadlines", {}))
        return [e["date"] for e in events]
