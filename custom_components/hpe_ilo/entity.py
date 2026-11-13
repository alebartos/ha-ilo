"""Entità base: un dispositivo per server."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_PROTOCOL, DOMAIN, PROTOCOL_REDFISH
from .coordinator import IloCoordinator


class IloEntity(CoordinatorEntity[IloCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: IloCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        data = coordinator.data
        self._attr_unique_id = f"{entry.unique_id}_{key}"
        scheme = "https" if entry.data[CONF_PROTOCOL] == PROTOCOL_REDFISH else "http"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=data.name or entry.title,
            manufacturer="HPE",
            model=data.model,
            serial_number=data.serial,
            sw_version=data.ilo_firmware,
            hw_version=f"BIOS {data.bios}" if data.bios else None,
            configuration_url=f"{scheme}://{entry.data['host']}",
        )
