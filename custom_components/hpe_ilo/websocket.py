"""Comandi websocket per la card termica (hpe-ilo-thermal-card)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN


def _loaded_entries(hass: HomeAssistant) -> list:
    return [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED and getattr(e, "runtime_data", None)
    ]


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_servers)
    websocket_api.async_register_command(hass, ws_thermal)


@websocket_api.websocket_command({vol.Required("type"): "hpe_ilo/servers"})
@callback
def ws_servers(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    connection.send_result(
        msg["id"], [{"entry_id": e.entry_id, "title": e.title} for e in _loaded_entries(hass)]
    )


@websocket_api.websocket_command(
    {vol.Required("type"): "hpe_ilo/thermal", vol.Optional("server"): str}
)
@callback
def ws_thermal(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    wanted = (msg.get("server") or "").strip().lower()
    entries = _loaded_entries(hass)
    entry = next(
        (e for e in entries if wanted in (e.entry_id.lower(), e.title.lower())),
        entries[0] if entries and not wanted else None,
    )
    if entry is None:
        connection.send_error(msg["id"], "not_found", f"Server iLO '{msg.get('server')}' non trovato")
        return

    data = entry.runtime_data.data
    sensors: list[dict[str, Any]] = []
    for meas in data.temperatures.values():
        x, y = meas.extra.get("x"), meas.extra.get("y")
        sensors.append(
            {
                "key": meas.key,
                "name": meas.name,
                "value": meas.value,
                "caution": meas.caution,
                "critical": meas.critical,
                "health": meas.health,
                "zone": meas.extra.get("posizione"),
                "x": x if isinstance(x, (int, float)) else None,
                "y": y if isinstance(y, (int, float)) else None,
            }
        )
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "model": data.model,
            "power_on": data.power_on,
            "has_map": any(s["x"] is not None and s["y"] is not None for s in sensors),
            "sensors": sensors,
            "pci": list(getattr(data, "pci_slots", None) or []),
            "last_update_success": entry.runtime_data.last_update_success,
        },
    )
