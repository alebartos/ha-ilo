"""Integrazione HP iLO: stato, sensori e alimentazione dei server HP ProLiant."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from . import websocket
from .api import RedfishClient, SshClient
from .const import CONF_PROTOCOL, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, PROTOCOL_REDFISH
from .coordinator import IloCoordinator

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = f"/{DOMAIN}/hpe-ilo-thermal-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "hpe-ilo-thermal-card.js"

IloConfigEntry = ConfigEntry[IloCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra la card termica e i comandi websocket (una volta sola)."""
    websocket.async_register(hass)
    integration = await async_get_integration(hass, DOMAIN)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), False)]
    )
    # caricata automaticamente in tutte le dashboard, niente risorsa da aggiungere a mano
    add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")
    return True


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
