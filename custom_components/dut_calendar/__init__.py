"""Tích hợp DUT Calendar (Lịch tuần công khai + Lịch coi thi/hạn nộp điểm)."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_TYPE,
    DOMAIN,
    TYPE_COITHI,
    TYPE_DEADLINE_DIEM,
    TYPE_LICHGIANGDAY,
    TYPE_LICHTUAN,
)
from .coordinator_exam import CBDutCoordinator
from .coordinator_public import LichTuanDutCoordinator

PLATFORMS = ["sensor", "calendar"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    entry_type = entry.data.get(CONF_TYPE)

    if entry_type == TYPE_LICHTUAN:
        coordinator = LichTuanDutCoordinator(hass, entry)
        await coordinator.async_config_entry_first_refresh()
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
    return unload_ok
