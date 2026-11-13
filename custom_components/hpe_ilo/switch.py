"""Interruttore di alimentazione: acceso = On, spento = spegnimento pulito."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IloConfigEntry
from .const import ACTION_ON, ACTION_SHUTDOWN
from .entity import IloEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant, entry: IloConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([IloPowerSwitch(entry.runtime_data, "power_switch")])


class IloPowerSwitch(IloEntity, SwitchEntity):
    _attr_translation_key = "power"
    _attr_device_class = SwitchDeviceClass.SWITCH

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.power_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_power(ACTION_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_power(ACTION_SHUTDOWN)
