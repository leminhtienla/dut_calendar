"""Tích hợp DUT Calendar (Lịch tuần công khai + Lịch coi thi/hạn nộp điểm)."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_TYPE,
    DOMAIN,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHGIANGDAY,
    TYPE_LICHTUAN,
    TYPE_MAIL,
)
from .coordinator_exam import CBDutCoordinator
from .coordinator_mail import DutMailCoordinator
from .coordinator_public import LichTuanDutCoordinator

PLATFORMS = ["sensor", "calendar", "select"]

SERVICE_NAP_GPA = "nap_gpa_sinh_vien"
SERVICE_AN_GPA = "an_gpa_sinh_vien"
_NAP_GPA_SCHEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_ids})
_AN_GPA_SCHEMA = vol.Schema({vol.Optional("entity_id"): cv.entity_ids})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Đăng ký service dùng chung cho cả domain — chạy đúng 1 lần, bất
    kể có bao nhiêu config entry.
    """

    async def _handle_nap_gpa(call: ServiceCall) -> None:
        """Tra GPA cho sinh viên ĐANG CHỌN trong entity 'Sinh viên'.

        CHỦ Ý đây là hành động phải gọi TƯỜNG MINH (qua service), GPA
        không bao giờ tự động tải kèm khi chọn lớp/chọn sinh viên —
        đúng nguyên tắc hạn chế tối đa tiếp xúc dữ liệu học tập của
        sinh viên, chỉ xem khi thật sự cần.

        Không truyền entity_id -> áp dụng cho MỌI entity đang có sẵn 1
        sinh viên được chọn (trường hợp phổ biến: chỉ có 1 entry loại
        'Lịch dạy Lớp').
        """
        entities = hass.data.get(DOMAIN, {}).get("_sv_select_entities", [])
        entity_ids = call.data.get("entity_id")
        if entity_ids:
            targets = [e for e in entities if e.entity_id in entity_ids]
        else:
            targets = [e for e in entities if e.co_sinh_vien_dang_chon()]
        for e in targets:
            await e.async_nap_gpa()

    async def _handle_an_gpa(call: ServiceCall) -> None:
        """Ẩn lại GPA đang hiển thị — không xóa cache, nạp lại sau đó
        gần như tức thì (xem `SinhVienSelect.async_an_gpa`).

        Không truyền entity_id -> áp dụng cho MỌI entity đang có GPA
        hiển thị.
        """
        entities = hass.data.get(DOMAIN, {}).get("_sv_select_entities", [])
        entity_ids = call.data.get("entity_id")
        if entity_ids:
            targets = [e for e in entities if e.entity_id in entity_ids]
        else:
            targets = [e for e in entities if e.co_gpa_dang_hien()]
        for e in targets:
            await e.async_an_gpa()

    hass.services.async_register(
        DOMAIN, SERVICE_NAP_GPA, _handle_nap_gpa, schema=_NAP_GPA_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_AN_GPA, _handle_an_gpa, schema=_AN_GPA_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get(CONF_TYPE)

    if entry_type == TYPE_LICHTUAN:
        coordinator = LichTuanDutCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
    elif entry_type == TYPE_MAIL:
        coordinator = DutMailCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()

        if not hass.is_running:
            # Lúc HA đang khởi động, coordinator CHƯA hỏi AI (tránh treo
            # bootstrap). Ngay khi HA khởi động xong, làm mới 1 lần để
            # xử lý các mail cần AI, khỏi phải đợi tới chu kỳ quét kế tiếp.
            async def _lam_moi_sau_khoi_dong(_event: Event) -> None:
                await coordinator.async_request_refresh()

            entry.async_on_unload(
                hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, _lam_moi_sau_khoi_dong
                )
            )
    elif entry_type in (TYPE_COITHI, TYPE_DEADLINE_DIEM, TYPE_LICHGIANGDAY):
        coordinator = CBDutCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
    else:
        raise ValueError(f"Loại config entry không hợp lệ: {entry_type!r}")

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        if isinstance(coordinator, CBDutCoordinator):
            await coordinator.async_close()
        # Dọn registry service nap_gpa_sinh_vien khỏi entity thuộc entry vừa gỡ.
        registry = hass.data.get(DOMAIN, {}).get("_sv_select_entities")
        if registry:
            hass.data[DOMAIN]["_sv_select_entities"] = [
                e for e in registry if getattr(e, "_entry", None) is not entry
            ]
    return unload_ok
