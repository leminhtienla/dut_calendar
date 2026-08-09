"""Chọn nhanh sinh viên để xem ảnh (không tải, không lưu ảnh).

Chỉ dựng ĐƯỜNG DẪN ảnh trên hệ thống trường rồi đưa ra thuộc tính; thẻ
Markdown trên dashboard sẽ hiển thị. Home Assistant KHÔNG tải, KHÔNG
lưu ảnh xuống đĩa, và danh sách sinh viên chỉ nằm trong bộ nhớ.

Danh sách sinh viên chỉ gồm MÃ SỐ + HỌ TÊN — số điện thoại và địa chỉ
trong bảng gốc không được đọc (xem parser_exam.parse_student_list).
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_TYPE, DOMAIN, TYPE_LICHGIANGDAY
from .coordinator_exam import CBDutCoordinator
from .parser_exam import anh_sinh_vien_url, parse_student_list

_LOGGER = logging.getLogger(__name__)

KHONG_CHON = "— Chưa chọn —"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    if (
        not isinstance(coordinator, CBDutCoordinator)
        or entry.data.get(CONF_TYPE) != TYPE_LICHGIANGDAY
    ):
        return

    lop = LopSelect(coordinator, entry)
    sv = SinhVienSelect(coordinator, entry, lop)
    lop.gan_o_sinh_vien(sv)
    async_add_entities([lop, sv])


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="DUT Calendar - Lịch dạy",
        manufacturer="cb.dut.udn.vn (không chính thức)",
        model="Lịch giảng dạy",
    )


class LopSelect(SelectEntity):
    """Chọn lớp học phần đang dạy."""

    _attr_has_entity_name = True
    _attr_name = "Lớp"
    _attr_icon = "mdi:google-classroom"

    def __init__(self, coordinator: CBDutCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._chon = KHONG_CHON
        self._o_sinh_vien: SinhVienSelect | None = None
        self._attr_unique_id = f"{entry.entry_id}_chon_lop"
        self._attr_device_info = _device_info(entry)

    def gan_o_sinh_vien(self, o: SinhVienSelect) -> None:
        self._o_sinh_vien = o

    def _cac_lop(self) -> dict[str, str]:
        """{nhãn hiển thị -> mã lớp}."""
        data = self._coordinator.data or {}
        out: dict[str, str] = {}
        for parsed in (data.get("lich_giang_day") or {}).values():
            for lop in parsed.get("lop_hoc", []):
                ma = str(lop.get("ma_lop") or "").strip()
                ten = str(lop.get("ten_lop") or "").strip()
                if ma:
                    out[f"{ten} ({ma})" if ten else ma] = ma
        return out

    @property
    def options(self) -> list[str]:
        return [KHONG_CHON] + sorted(self._cac_lop())

    @property
    def current_option(self) -> str:
        return self._chon if self._chon in self.options else KHONG_CHON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"ma_lop": self._cac_lop().get(self._chon)}

    async def async_select_option(self, option: str) -> None:
        self._chon = option
        self.async_write_ha_state()
        if self._o_sinh_vien is not None:
            await self._o_sinh_vien.nap_danh_sach(self._cac_lop().get(option))


class SinhVienSelect(SelectEntity):
    """Chọn sinh viên trong lớp đã chọn; xuất đường dẫn ảnh."""

    _attr_has_entity_name = True
    _attr_name = "Sinh viên"
    _attr_icon = "mdi:account-search"

    def __init__(
        self, coordinator: CBDutCoordinator, entry: ConfigEntry, o_lop: LopSelect
    ) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._o_lop = o_lop
        self._danh_sach: list[dict[str, str]] = []
        self._chon = KHONG_CHON
        self._attr_unique_id = f"{entry.entry_id}_chon_sinh_vien"
        self._attr_device_info = _device_info(entry)

    def _nhan(self, sv: dict[str, str]) -> str:
        return f"{sv['ho_ten']} ({sv['ma_sv']})"

    async def nap_danh_sach(self, ma_lop: str | None) -> None:
        """Tải danh sách sinh viên của lớp vừa chọn (chỉ mã + họ tên)."""
        self._danh_sach = []
        self._chon = KHONG_CHON
        if ma_lop:
            try:
                raw = await self._coordinator.client.fetch_student_list_html(ma_lop)
                self._danh_sach = await self.hass.async_add_executor_job(
                    parse_student_list, raw
                )
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("Không lấy được danh sách sinh viên lớp %s: %s", ma_lop, err)
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        return [KHONG_CHON] + [self._nhan(sv) for sv in self._danh_sach]

    @property
    def current_option(self) -> str:
        return self._chon if self._chon in self.options else KHONG_CHON

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sv = next((x for x in self._danh_sach if self._nhan(x) == self._chon), None)
        return {
            "ma_sv": sv["ma_sv"] if sv else None,
            "ho_ten": sv["ho_ten"] if sv else None,
            # Chỉ là ĐƯỜNG DẪN tới ảnh trên máy chủ trường — HA không tải về.
            "anh_url": anh_sinh_vien_url(sv["ma_sv"]) if sv else None,
            "so_sinh_vien": len(self._danh_sach),
        }

    async def async_select_option(self, option: str) -> None:
        self._chon = option
        self.async_write_ha_state()
