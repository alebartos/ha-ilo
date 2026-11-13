"""Integrazione HP iLO: stato, sensori e alimentazione dei server HP ProLiant."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import RedfishClient, SshClient
from .const import CONF_PROTOCOL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, PROTOCOL_REDFISH
from .coordinator import IloCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]

IloConfigEntry = ConfigEntry[IloCoordinator]


def create_client(hass: HomeAssistant, data: dict) -> RedfishClient | SshClient:
    """Crea il client adatto al protocollo salvato nella configurazione."""
    if data[CONF_PROTOCOL] == PROTOCOL_REDFISH:
        return RedfishClient(
            async_get_clientsession(hass, verify_ssl=False),
            data[CONF_HOST],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
    return SshClient(
        hass.async_add_executor_job, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD]
    )


async def async_setup_entry(hass: HomeAssistant, entry: IloConfigEntry) -> bool:
    protocol = entry.data[CONF_PROTOCOL]
    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL[protocol])
    coordinator = IloCoordinator(hass, entry, create_client(hass, entry.data), interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: IloConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: IloConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
