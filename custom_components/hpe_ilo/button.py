"""Pulsanti: accendi, spegnimento pulito, spegnimento forzato, riavvio forzato."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IloConfigEntry
from .const import ACTION_FORCE_OFF, ACTION_ON, ACTION_RESET, ACTION_SHUTDOWN
from .coordinator import IloCoordinator
from .entity import IloEntity

PARALLEL_UPDATES = 1

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(key=ACTION_ON, translation_key="power_on", icon="mdi:power-on"),
    ButtonEntityDescription(key=ACTION_SHUTDOWN, translation_key="shutdown", icon="mdi:power-off"),
    ButtonEntityDescription(
        key=ACTION_FORCE_OFF, translation_key="force_off", icon="mdi:power-plug-off"
    ),
    ButtonEntityDescription(
        key=ACTION_RESET, translation_key="reset", device_class=ButtonDeviceClass.RESTART
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: IloConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(IloButton(entry.runtime_data, desc) for desc in BUTTONS)


class IloButton(IloEntity, ButtonEntity):
    def __init__(self, coordinator: IloCoordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator, f"button_{description.key}")
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_power(self.entity_description.key)
