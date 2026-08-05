"""Calendar cho DUT Calendar — nhánh theo loại coordinator (public/exam)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_TYPE,
    DEFAULT_MEETING_DURATION,
    DOMAIN,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHGIANGDAY,
)
from .coordinator_exam import CBDutCoordinator
from .coordinator_mail import DutMailCoordinator
from .coordinator_public import LichTuanDutCoordinator
from .parser_exam import build_deadline_events, format_hoc_ky
from .parser_public import parse_event_datetime


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]

    if isinstance(coordinator, DutMailCoordinator):
        async_add_entities([MailMeetingCalendar(coordinator, entry)])
    elif isinstance(coordinator, LichTuanDutCoordinator):
        async_add_entities([PublicScheduleCalendar(coordinator, entry)])
    elif isinstance(coordinator, CBDutCoordinator):
        entry_type = entry.data.get(CONF_TYPE)
        if entry_type == TYPE_COITHI:
            async_add_entities([ExamDutyCalendar(coordinator, entry)])
        elif entry_type == TYPE_DEADLINE_DIEM:
            async_add_entities([DeadlineCalendar(coordinator, entry)])
        elif entry_type == TYPE_LICHGIANGDAY:
            async_add_entities([TeachingCalendar(coordinator, entry)])


def _end_as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value) + timedelta(days=1)


def _start_as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return dt_util.start_of_local_day(value)


# =====================================================================
# Nguồn 1: Lịch tuần công khai
# =====================================================================
class PublicScheduleCalendar(CoordinatorEntity[LichTuanDutCoordinator], CalendarEntity):
    """Lịch gồm mọi mục đang khớp bất kỳ nhóm từ khóa nào đã cấu hình."""

    # Lấy thẳng tên thiết bị làm tên entity (name=None) để danh sách
    # lịch không hiện lặp "DUT Calendar - X X".
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:calendar-text"

    def __init__(self, coordinator: LichTuanDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Lịch tuần",
            manufacturer="lichtuan.dut.udn.vn (không chính thức)",
            model="Cảnh báo từ khóa",
        )

    def _build_events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        tzinfo = dt_util.DEFAULT_TIME_ZONE
        events: list[CalendarEvent] = []

        for m in data.get("matches", []):
            start, end, all_day = parse_event_datetime(m.get("date", ""), m.get("time", ""))
            if start is None:
                continue
            if not all_day:
                start = start.replace(tzinfo=tzinfo)
                end = end.replace(tzinfo=tzinfo)

            kw = ", ".join(m.get("matched_keywords", []))
            variants = ", ".join(m.get("matched_variants", []))
            desc_lines = [f"Từ khóa khớp: {kw} ({variants})"]
            if m.get("phu_luc"):
                desc_lines.append("(Nguồn: bảng Phụ lục)")
            if m.get("participants"):
                desc_lines.append(f"Thành phần: {m['participants']}")
            if m.get("host"):
                desc_lines.append(f"Chủ trì: {m['host']}")
            if m.get("week_label"):
                desc_lines.append(f"Tuần: {m['week_label']}")

            prefix = f"[{kw}] " if kw else ""

            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=f"{prefix}{m.get('content') or '(không có nội dung)'}",
                    description="\n".join(desc_lines),
                    location=m.get("location") or "",
                    uid=m.get("id"),
                )
            )

        events.sort(key=lambda e: _start_as_datetime(e.start))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._build_events() if _end_as_datetime(e.end) >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        result = []
        for e in self._build_events():
            e_start = _start_as_datetime(e.start)
            e_end = _end_as_datetime(e.end)
            if e_end >= start_date and e_start <= end_date:
                result.append(e)
        return result


# =====================================================================
# Nguồn 2: Lịch coi thi & hạn nộp điểm
# =====================================================================
class ExamDutyCalendar(CoordinatorEntity[CBDutCoordinator], CalendarEntity):
    """Lịch gồm mọi ca coi thi đã đăng ký trong các học kỳ đang theo dõi."""

    # Lấy thẳng tên thiết bị làm tên entity (name=None) để danh sách
    # lịch không hiện lặp "DUT Calendar - X X".
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Coi thi",
            manufacturer="cb.dut.udn.vn (không chính thức)",
            model="Cảnh báo lịch coi thi",
        )

    def _build_events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        tzinfo = dt_util.DEFAULT_TIME_ZONE
        events: list[CalendarEvent] = []

        for d in data.get("duties", []):
            start, end = d.get("start"), d.get("end")
            if start is None or end is None:
                continue
            start = start.replace(tzinfo=tzinfo)
            end = end.replace(tzinfo=tzinfo)

            desc_lines = [f"Mã ca thi: {d.get('ma_ca_thi')}"]
            desc_lines.append(f"Cán bộ 1: {d.get('can_bo_1') or '(trống)'}")
            desc_lines.append(f"Cán bộ 2: {d.get('can_bo_2') or '(trống)'}")
            if d.get("xuat"):
                desc_lines.append(f"Xuất: {d['xuat']}")
            if d.get("hoc_ky_label"):
                desc_lines.append(f"Học kỳ: {format_hoc_ky(d['hoc_ky_label'])}")

            # Tiêu đề: [Tên · GT<vai trò>] Coi thi: <môn> — Phòng <phòng>
            # Áp dụng cho CẢ ca của chính mình lẫn ca của giảng viên
            # khác đang theo dõi (trước đây chỉ ca giảng viên khác mới
            # có tên trong tiêu đề, ca của chính mình không có gì).
            name = d.get("target_name")
            role = d.get("role")
            if name:
                role_txt = f" · GT{role}" if role else ""
                prefix = f"[{name}{role_txt}] "
            else:
                prefix = ""
            phong_txt = f" — Phòng {d['phong']}" if d.get("phong") else ""

            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=(
                        f"{prefix}Coi thi: {d.get('mon_thi') or '(không rõ môn)'}{phong_txt}"
                    ),
                    description="\n".join(desc_lines),
                    location=d.get("phong") or "",
                    uid=d.get("id"),
                )
            )

        events.sort(key=lambda e: e.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._build_events() if e.end >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._build_events() if e.end >= start_date and e.start <= end_date]


# =====================================================================
# Nguồn: Hạn nộp điểm — mỗi mốc hạn là 1 sự kiện CẢ NGÀY
# =====================================================================
class DeadlineCalendar(CoordinatorEntity[CBDutCoordinator], CalendarEntity):
    """Lịch gồm mọi mốc hạn nộp điểm (thi chung + từng lớp) đang theo dõi."""

    # Lấy thẳng tên thiết bị làm tên entity (name=None) để danh sách
    # lịch không hiện lặp "DUT Calendar - X X".
    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Nhập điểm",
            manufacturer="cb.dut.udn.vn (không chính thức)",
            model="Cảnh báo hạn nộp điểm",
        )

    def _build_events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        grade_deadlines = data.get("grade_deadlines", {})
        raw_events = build_deadline_events(grade_deadlines)

        events = [
            CalendarEvent(
                start=e["date"],
                end=e["date"] + timedelta(days=1),
                summary=("✓ " if e.get("da_xong") else "") + e["summary"],
                description=f"Học kỳ: {format_hoc_ky(e['hoc_ky'])}",
                uid=f"{self._entry.entry_id}_{e['hoc_ky']}_{e.get('ma_lop', 'chung')}_{e['summary']}",
            )
            for e in raw_events
        ]
        events.sort(key=lambda ev: _start_as_datetime(ev.start))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._build_events() if _end_as_datetime(e.end) >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        result = []
        for e in self._build_events():
            e_start = _start_as_datetime(e.start)
            e_end = _end_as_datetime(e.end)
            if e_end >= start_date and e_start <= end_date:
                result.append(e)
        return result


# =====================================================================
# Nguồn: Lịch giảng dạy — từng buổi dạy cụ thể (ngày + giờ + phòng)
# =====================================================================
class TeachingCalendar(CoordinatorEntity[CBDutCoordinator], CalendarEntity):
    """Lịch các buổi lên lớp, dựng từ thời khóa biểu của học kỳ."""

    # Lấy thẳng tên thiết bị làm tên entity (name=None) để danh sách
    # lịch không hiện lặp "DUT Calendar - X X".
    _attr_has_entity_name = True
    _attr_name = None
    # KHÔNG đặt icon riêng -> dùng icon mặc định chuẩn của Home Assistant
    # cho entity calendar. (Trước đây dùng "mdi:teach" nhưng MDI đã đổi
    # tên icon này thành "human-male-board" nên hiện ra ô trống.)

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar_giangday"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Lịch dạy",
            manufacturer="cb.dut.udn.vn (không chính thức)",
            model="Lịch giảng dạy",
        )

    def _build_events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        tzinfo = dt_util.DEFAULT_TIME_ZONE
        events: list[CalendarEvent] = []

        for b in data.get("buoi_day", []):
            start, end = b.get("start"), b.get("end")
            if start is None or end is None:
                continue
            events.append(
                CalendarEvent(
                    start=start.replace(tzinfo=tzinfo),
                    end=end.replace(tzinfo=tzinfo),
                    # Tiêu đề gọn: chỉ icon + tên lớp + phòng.
                    # Chi tiết (nghỉ/bù, tiết, tuần, mã lớp) nằm ở mô tả.
                    # Tiêu đề gọn: icon trạng thái + [tên người] (chỉ khi
                    # theo dõi thêm người khác, để phân biệt) + lớp · phòng.
                    summary=(
                        ("🚫 " if b.get("da_nghi") else "")
                        + ("🔁 " if b.get("la_day_bu") else "")
                        + (f"[{b['nguoi']}] " if b.get("nguoi") else "")
                        + f"{b.get('ten_lop') or '(lớp)'} · {b.get('phong')}"
                        + (
                            f" · tiết {b['tiet']}"
                            + (f" ({b['so_tiet']} tiết)" if b.get("so_tiet") else "")
                            if b.get("tiet")
                            else ""
                        )
                    ),
                    description=(
                        (f"Giảng viên: {b['nguoi']}\n" if b.get("nguoi") else "")
                        + f"Mã lớp: {b.get('ma_lop')}\n"
                        f"Tiết: {b.get('tiet')}\n"
                        f"Tuần học: {b.get('tuan')}"
                        + ("\nBuổi này ĐÃ BÁO NGHỈ" if b.get("da_nghi") else "")
                        + ("\nĐây là buổi DẠY BÙ" if b.get("la_day_bu") else "")
                    ),
                    location=b.get("phong") or "",
                    uid=f"{self._entry.entry_id}_{b.get('ma_lop')}_{start.isoformat()}",
                )
            )
        events.sort(key=lambda ev: _start_as_datetime(ev.start))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._build_events() if _end_as_datetime(e.end) >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        result = []
        for e in self._build_events():
            if _end_as_datetime(e.end) >= start_date and _start_as_datetime(e.start) <= end_date:
                result.append(e)
        return result



# =====================================================================
# Nguồn: Email — cuộc họp tách được từ mail (chỉ mail có đủ ngày+giờ)
# =====================================================================
class MailMeetingCalendar(CoordinatorEntity[DutMailCoordinator], CalendarEntity):
    """Lịch các cuộc họp lấy từ email khớp từ khóa.

    Chỉ tạo sự kiện cho mail tách được ĐẦY ĐỦ ngày + giờ bằng quy tắc;
    mail không tách được vẫn báo bình thường nhưng không lên lịch —
    thà thiếu còn hơn đặt sai giờ.
    """

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: DutMailCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_calendar_mail"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Email",
            manufacturer="IMAP (không chính thức)",
            model="Cảnh báo email theo từ khóa",
        )

    def _build_events(self) -> list[CalendarEvent]:
        data = self.coordinator.data or {}
        tzinfo = dt_util.DEFAULT_TIME_ZONE
        events: list[CalendarEvent] = []

        for m in data.get("matches", []):
            raw = m.get("meeting_start")
            if not raw:
                continue
            try:
                start = datetime.fromisoformat(raw)
            except (TypeError, ValueError):
                continue
            end = start + timedelta(minutes=DEFAULT_MEETING_DURATION)

            desc = [f"Người gửi: {m.get('sender')}"]
            if m.get("thoi_gian_raw"):
                desc.append(f"Thời gian (nguyên văn): {m['thoi_gian_raw']}")
            if m.get("thanh_phan_raw"):
                desc.append(f"Thành phần: {m['thanh_phan_raw']}")
            if m.get("matched_keywords"):
                desc.append(f"Từ khóa khớp: {', '.join(m['matched_keywords'])}")

            events.append(
                CalendarEvent(
                    start=start.replace(tzinfo=tzinfo),
                    end=end.replace(tzinfo=tzinfo),
                    summary=m.get("subject") or "(không có tiêu đề)",
                    description="\n".join(desc),
                    location=m.get("meeting_location") or "",
                    uid=f"{self._entry.entry_id}_{m.get('id')}",
                )
            )
        events.sort(key=lambda ev: _start_as_datetime(ev.start))
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._build_events() if _end_as_datetime(e.end) >= now]
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [
            e
            for e in self._build_events()
            if _end_as_datetime(e.end) >= start_date and _start_as_datetime(e.start) <= end_date
        ]
