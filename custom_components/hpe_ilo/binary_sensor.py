"""Sensori binari: server acceso e problema di salute."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IloConfigEntry
from .const import HEALTH_OK
from .entity import IloEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant, entry: IloConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([IloPowerState(coordinator, "power_state"), IloProblem(coordinator, "problem")])


class IloPowerState(IloEntity, BinarySensorEntity):
    _attr_translation_key = "power_state"
    _attr_device_class = BinarySensorDeviceClass.POWER

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.power_on


class IloProblem(IloEntity, BinarySensorEntity):
    _attr_translation_key = "problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        health = self.coordinator.data.health
        return None if health is None else health != HEALTH_OK
