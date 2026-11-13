"""Sensori: consumo, salute, temperature, tensioni, ventole, alimentatori."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential, UnitOfPower, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import IloConfigEntry
from .api import IloData, Measurement
from .const import HEALTH_OK
from .coordinator import IloCoordinator
from .entity import IloEntity

PARALLEL_UPDATES = 0


def _average(values: list[Any]) -> float | None:
    nums = [v for v in values if isinstance(v, (int, float))]
    return round(sum(nums) / len(nums), 1) if nums else None


@dataclass(frozen=True, kw_only=True)
class IloSensorDescription(SensorEntityDescription):
    value_fn: Callable[[IloData], Any]


SYSTEM_SENSORS: tuple[IloSensorDescription, ...] = (
    IloSensorDescription(
        key="power",
        translation_key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.power_watts,
    ),
    IloSensorDescription(
        key="power_avg",
        translation_key="power_avg",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda d: d.power_avg,
    ),
    IloSensorDescription(
        key="power_min",
        translation_key="power_min",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.power_min,
    ),
    IloSensorDescription(
        key="power_max",
        translation_key="power_max",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        entity_registry_enabled_default=False,
        value_fn=lambda d: d.power_max,
    ),
    IloSensorDescription(
        key="fan_avg",
        translation_key="fan_avg",
        icon="mdi:fan",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d: _average([m.value for m in d.fans.values()]),
    ),
    IloSensorDescription(
        key="health",
        translation_key="health",
        device_class=SensorDeviceClass.ENUM,
        options=[HEALTH_OK, "warning", "critical"],
        value_fn=lambda d: d.health if d.health in (HEALTH_OK, "warning", "critical") else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: IloConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SensorEntity] = [
        IloSystemSensor(coordinator, desc)
        for desc in SYSTEM_SENSORS
        if desc.value_fn(data) is not None or desc.key in ("power", "health")
    ]
    for key in data.temperatures:
        entities.append(IloMeasurementSensor(coordinator, "temperatures", key))
    for key in data.voltages:
        entities.append(IloMeasurementSensor(coordinator, "voltages", key))
    for key in data.fans:
        entities.append(IloMeasurementSensor(coordinator, "fans", key))
    for key in data.power_supplies:
        entities.append(IloMeasurementSensor(coordinator, "power_supplies", key))
    async_add_entities(entities)


class IloSystemSensor(IloEntity, SensorEntity):
    entity_description: IloSensorDescription

    def __init__(self, coordinator: IloCoordinator, description: IloSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)


class IloMeasurementSensor(IloEntity, SensorEntity):
    """Una lettura dinamica: il nome arriva dall'iLO."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: IloCoordinator, group: str, key: str) -> None:
        super().__init__(coordinator, f"{group}_{key}")
        self._group = group
        self._key = key
        meas = self._measurement
        assert meas is not None
        self._attr_entity_registry_enabled_default = meas.primary
        if group == "temperatures":
            self._attr_name = f"Temperatura {meas.name}"
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif group == "voltages":
            self._attr_name = f"Tensione {meas.name}"
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        elif group == "fans":
            self._attr_name = meas.name.replace("Fan Block", "Ventola").replace("Fan", "Ventola")
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_icon = "mdi:fan"
        else:  # alimentatori
            self._attr_name = meas.name
            self._attr_icon = "mdi:power-plug"
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
            if isinstance(meas.value, str):
                self._attr_state_class = None
            else:
                self._attr_device_class = SensorDeviceClass.POWER
                self._attr_native_unit_of_measurement = UnitOfPower.WATT

    @property
    def _measurement(self) -> Measurement | None:
        return getattr(self.coordinator.data, self._group).get(self._key)

    @property
    def available(self) -> bool:
        return super().available and self._measurement is not None

    @property
    def native_value(self) -> Any:
        meas = self._measurement
        return meas.value if meas else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        meas = self._measurement
        if meas is None:
            return None
        attrs: dict[str, Any] = {"salute": meas.health}
        if meas.caution is not None:
            attrs["soglia_attenzione"] = meas.caution
        if meas.critical is not None:
            attrs["soglia_critica"] = meas.critical
        attrs.update({k: v for k, v in meas.extra.items() if v not in (None, "")})
        return attrs
