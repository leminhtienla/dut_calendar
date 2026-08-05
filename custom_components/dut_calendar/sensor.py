"""Sensor cho DUT Calendar — nhánh theo loại coordinator (public/exam)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_TYPE, DOMAIN, TYPE_COITHI, TYPE_DEADLINE_DIEM, TYPE_LICHGIANGDAY
from .coordinator_exam import CBDutCoordinator
from .coordinator_public import LichTuanDutCoordinator
from .parser_exam import build_deadline_events, format_hoc_ky, parse_vn_date
from .parser_public import parse_event_datetime

MAX_ATTR_ENTRIES = 25
PERIODS = ("today", "tomorrow", "week", "next_week", "month")


def _purge_stale_sensors(
    hass: HomeAssistant, entry: ConfigEntry, valid_unique_ids: set[str]
) -> None:
    """Xóa khỏi entity registry các sensor CŨ của entry này mà lần cấu
    hình hiện tại không còn tạo nữa.

    Cần thiết vì `dut_lichtuan` tạo sensor theo TỪNG nhóm từ khóa —
    khi người dùng đổi/xóa/đổi tên nhóm trong Options, sensor của nhóm
    cũ không tự biến mất mà nằm lại vĩnh viễn ở trạng thái "không khả
    dụng", gây rác trong danh sách entity.

    Chỉ đụng tới entity thuộc domain "sensor" của ĐÚNG entry này, nên
    không ảnh hưởng Calendar hay các entry khác.
    """
    registry = er.async_get(hass)
    for entity in list(er.async_entries_for_config_entry(registry, entry.entry_id)):
        if entity.domain != "sensor":
            continue
        if entity.unique_id not in valid_unique_ids:
            registry.async_remove(entity.entity_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    if isinstance(coordinator, LichTuanDutCoordinator):
        entities: list[SensorEntity] = [PublicTotalSensor(coordinator, entry)]
        labels = coordinator.keyword_labels
        for label in labels:
            entities.append(PublicKeywordSensor(coordinator, entry, label))
        # Bộ đếm TỔNG (mọi nhóm gộp lại)
        entities += [
            PublicCountSensor(coordinator, entry, period) for period in PERIODS
        ]
        # Bộ đếm RIÊNG cho từng nhóm từ khóa
        for label in labels:
            entities += [
                PublicCountSensor(coordinator, entry, period, keyword_label=label)
                for period in PERIODS
            ]
        # Dọn sensor của nhóm từ khóa đã bị xóa/đổi tên TRƯỚC khi thêm
        # mới, để entity_id cũ được giải phóng (tránh HA tự thêm hậu tố
        # _2 nếu nhóm mới trùng tên với nhóm cũ vừa bị xóa).
        _purge_stale_sensors(hass, entry, {e.unique_id for e in entities})
        async_add_entities(entities)
    elif isinstance(coordinator, CBDutCoordinator):
        entry_type = entry.data.get(CONF_TYPE)
        if entry_type == TYPE_COITHI:
            exam_entities: list[SensorEntity] = [ExamDutySensor(coordinator, entry)] + [
                CoithiCountSensor(coordinator, entry, period) for period in PERIODS
            ]
            _purge_stale_sensors(hass, entry, {e.unique_id for e in exam_entities})
            async_add_entities(exam_entities)
        elif entry_type == TYPE_DEADLINE_DIEM:
            dl_entities: list[SensorEntity] = [
                GradeDeadlineSensor(coordinator, entry),
                DeadlineTodoSensor(coordinator, entry),
            ] + [DeadlineCountSensor(coordinator, entry, period) for period in PERIODS]
            _purge_stale_sensors(hass, entry, {e.unique_id for e in dl_entities})
            async_add_entities(dl_entities)
        elif entry_type == TYPE_LICHGIANGDAY:
            lgd_entities: list[SensorEntity] = [
                TeachingCountSensor(coordinator, entry, period) for period in PERIODS
            ]
            _purge_stale_sensors(hass, entry, {e.unique_id for e in lgd_entities})
            async_add_entities(lgd_entities)


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
        name="DUT Calendar - Nhập điểm",
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
                "hoc_ky": format_hoc_ky(d.get("hoc_ky_label") or ""),
                "giang_vien_khac": d.get("extra_lecturer_match", False),
                "ten": d.get("target_name"),
                "giam_thi_so": d.get("role"),
            }
            for d in self._upcoming[:MAX_ATTR_ENTRIES]
        ]
        return {
            "hoc_ky_theo_doi": self.coordinator.hoc_ky_list,
            "giang_vien_khac_theo_doi": self.coordinator.extra_lecturers,
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

    def _all_deadline_dates(self) -> list[date]:
        """Gom MỌI mốc hạn (cả đã qua lẫn sắp tới) của các học kỳ đang theo dõi."""
        dates: list[date] = []
        for hk_info in self._deadlines.values():
            ca_thi_chung = hk_info.get("ca_thi_chung") or {}
            for key in ("ngay_ket_thuc", "ngay_nop_ban_diem", "han_dinh_chinh"):
                d = parse_vn_date(ca_thi_chung.get(key))
                if d:
                    dates.append(d)

            for lop_info in hk_info.get("theo_lop", {}).values():
                for key in (
                    "ngay_giua_ky",
                    "ngay_thanh_phan",
                    "ngay_cuoi_ky",
                    "han_dinh_chinh_giua_ky",
                    "han_dinh_chinh_thanh_phan",
                ):
                    d = parse_vn_date(lop_info.get(key))
                    if d:
                        dates.append(d)
        return dates

    @property
    def native_value(self) -> date | None:
        today = dt_util.now().date()
        candidates = [d for d in self._all_deadline_dates() if d >= today]
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
        today = dt_util.now().date()
        all_dates = self._all_deadline_dates()
        upcoming = [d for d in all_dates if d >= today]
        past = [d for d in all_dates if d < today]

        # Phân biệt rõ 3 tình huống đều khiến state hiện "Unknown"
        # (device_class=date nên không thể dùng 0 như các sensor đếm):
        if upcoming:
            trang_thai = "con_han_sap_toi"
        elif all_dates:
            trang_thai = "da_qua_het_han"  # có dữ liệu, nhưng mọi mốc đều đã qua
        else:
            trang_thai = "chua_co_du_lieu"  # chưa lấy được / trường chưa công bố

        return {
            "hoc_ky_theo_doi": self.coordinator.hoc_ky_list,
            "trang_thai": trang_thai,
            "so_moc_sap_toi": len(upcoming),
            "so_moc_da_qua": len(past),
            "han_gan_nhat_da_qua": max(past).strftime("%d/%m/%Y") if past else None,
            "chi_tiet_theo_hoc_ky": result,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


# =====================================================================
# Sensor đếm số sự kiện: Hôm nay / Ngày mai / Tháng này
# (dùng chung cho cả 3 loại, mỗi loại override _event_dates())
# =====================================================================
_PERIOD_LABELS = {
    "today": "Hôm nay",
    "tomorrow": "Ngày mai",
    "week": "Tuần này",
    "next_week": "Tuần sau",
    "month": "Tháng này",
}
_PERIOD_ICONS = {
    "today": "mdi:calendar-today",
    "tomorrow": "mdi:calendar-arrow-right",
    "week": "mdi:calendar-week",
    "next_week": "mdi:calendar-week-begin",
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
        if self._period in ("week", "next_week"):
            week_start = today - timedelta(days=today.weekday())  # Thứ 2 tuần này
            if self._period == "next_week":
                week_start += timedelta(days=7)
            week_end = week_start + timedelta(days=6)  # Chủ nhật
            return sum(1 for d in dates if week_start <= d <= week_end)
        # "month"
        return sum(1 for d in dates if d.year == today.year and d.month == today.month)


class PublicCountSensor(_CountSensorBase):
    """Đếm số mục lịch tuần khớp từ khóa theo từng khoảng thời gian.

    Nếu `keyword_label` được truyền vào, CHỈ đếm các mục thuộc đúng
    nhóm từ khóa đó (dùng để tạo bộ sensor đếm RIÊNG cho từng nhóm,
    bên cạnh bộ đếm TỔNG khi không truyền tham số này).
    """

    def __init__(
        self,
        coordinator: LichTuanDutCoordinator,
        entry: ConfigEntry,
        period: str,
        keyword_label: str | None = None,
    ) -> None:
        super().__init__(coordinator, entry, period)
        self._attr_device_info = _device_info_public(entry)
        self._keyword_label = keyword_label
        if keyword_label:
            period_label = _PERIOD_LABELS[period]
            self._attr_name = f"{keyword_label}: {period_label}"
            kw_hash = hashlib.sha1(keyword_label.strip().lower().encode("utf-8")).hexdigest()[:12]
            self._attr_unique_id = f"{entry.entry_id}_count_{period}_{kw_hash}"

    def _event_dates(self) -> list[date]:
        data = self.coordinator.data or {}
        dates: list[date] = []
        for m in data.get("matches", []):
            if self._keyword_label and self._keyword_label not in m.get("matched_keywords", []):
                continue
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


# =====================================================================
# Sensor "Cần nhập điểm" — danh sách việc cần làm, sắp theo hạn gần nhất
# =====================================================================
class DeadlineTodoSensor(CoordinatorEntity[CBDutCoordinator], SensorEntity):
    """Trả lời trực tiếp: còn bao nhiêu mốc nhập điểm chưa quá hạn, môn
    nào, loại điểm gì, còn mấy ngày.

    Khác với sensor `Hạn nộp điểm` (chỉ cho biết NGÀY gần nhất) và các
    sensor đếm theo khoảng (chỉ cho con SỐ), sensor này đưa nguyên
    danh sách việc cần làm đã sắp xếp — dùng thẳng trong automation/
    template mà không phải tự đào vào cấu trúc lồng theo học kỳ/lớp.
    """

    _attr_has_entity_name = True
    _attr_name = "Cần nhập điểm"
    _attr_icon = "mdi:clipboard-edit-outline"
    _attr_native_unit_of_measurement = "mốc"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_deadline_todo"
        self._attr_device_info = _device_info_deadline(entry)

    def _pending(self) -> list[dict[str, Any]]:
        """Các mốc CHƯA quá hạn, kèm số ngày còn lại, sắp xếp gần → xa."""
        data = self.coordinator.data or {}
        today = dt_util.now().date()
        events = build_deadline_events(data.get("grade_deadlines", {}))

        pending = []
        for e in events:
            d = e["date"]
            if d < today:
                continue
            # Bỏ các mốc ĐÃ HOÀN THÀNH (đã xác nhận nhập điểm / đã nộp
            # bảng điểm) — chỉ liệt kê việc CÒN PHẢI LÀM.
            if e.get("da_xong"):
                continue
            pending.append(
                {
                    "ngay": d.strftime("%d/%m/%Y"),
                    "con_lai_ngay": (d - today).days,
                    "mon": e.get("ten_lop") or "(thi chung)",
                    "nhom": e.get("nhom"),
                    "da_xong": False,
                    "loai": e.get("loai"),
                    "loai_han": e.get("loai_han"),
                    "hoc_ky": e.get("hoc_ky"),
                    "hoc_ky_ten": format_hoc_ky(e.get("hoc_ky") or ""),
                    "ma_lop": e.get("ma_lop"),
                    "_sort": d,
                }
            )
        pending.sort(key=lambda x: (x["_sort"], x["mon"] or ""))
        for x in pending:
            x.pop("_sort")
        return pending

    @property
    def native_value(self) -> int:
        return len(self._pending())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        pending = self._pending()
        return {
            "hom_nay": [x for x in pending if x["con_lai_ngay"] == 0],
            "trong_7_ngay": [x for x in pending if x["con_lai_ngay"] <= 7],
            "gan_nhat": pending[0] if pending else None,
            # Tách riêng 2 nhóm hạn khác bản chất, để automation dùng thẳng
            "can_nhap_diem": [x for x in pending if x.get("loai_han") == "nhap_diem"],
            "can_nop_ban_in": [x for x in pending if x.get("loai_han") == "nop_ban_in"],
            "can_dinh_chinh": [x for x in pending if x.get("loai_han") == "dinh_chinh"],
            "danh_sach": pending[:MAX_ATTR_ENTRIES],
            "hoc_ky_theo_doi": self.coordinator.hoc_ky_list,
            "last_checked": datetime.now().isoformat(timespec="seconds"),
        }


def _device_info_lichgiangday(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Lịch dạy",
        manufacturer="cb.dut.udn.vn (không chính thức)",
        model="Lịch giảng dạy",
    )


class TeachingCountSensor(_CountSensorBase):
    """Đếm số buổi lên lớp theo hôm nay/ngày mai/tuần này/tuần sau/tháng này.

    Buổi đã báo nghỉ KHÔNG được tính (vì thực tế không lên lớp); buổi
    dạy bù thì có tính.
    """

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry, period: str) -> None:
        super().__init__(coordinator, entry, period)
        self._attr_device_info = _device_info_lichgiangday(entry)

    def _event_dates(self) -> list[date]:
        data = self.coordinator.data or {}
        return [
            b["start"].date()
            for b in data.get("buoi_day", [])
            if b.get("start") and not b.get("da_nghi")
        ]
