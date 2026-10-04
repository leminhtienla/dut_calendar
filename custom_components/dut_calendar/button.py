"""Nút bấm cho nguồn Email: "Quét lại toàn bộ mail"."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator_mail import DutMailCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    # Chỉ nguồn Email có nút này; các loại entry khác bỏ qua.
    if not isinstance(coordinator, DutMailCoordinator):
        return
    async_add_entities([DutMailFreshLoadButton(coordinator, entry)])


class DutMailFreshLoadButton(ButtonEntity):
    """Quét lại TOÀN BỘ mail từ đầu — mức SẠCH.

    Xóa lịch sử, bộ nhớ UID và cả kết quả AI đã có, rồi quét ngay. Mail
    nào luật không tách được sẽ bị hỏi lại AI (mỗi lượt tối đa vài mail,
    phần còn lại tự quét bù). Mail cũ nạp nền, không bắn thông báo.
    """

    _attr_has_entity_name = True
    _attr_name = "Quét lại toàn bộ mail"
    _attr_icon = "mdi:email-sync"

    def __init__(self, coordinator: DutMailCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_button_fresh_load_mail"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="DUT Calendar - Email",
            manufacturer="IMAP (không chính thức)",
            model="Cảnh báo email theo từ khóa",
        )

    async def async_press(self) -> None:
        await self._coordinator.async_fresh_load()
