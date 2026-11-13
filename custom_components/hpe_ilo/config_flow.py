"""Configurazione da interfaccia: host e credenziali, protocollo rilevato da solo."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import IloAuthError, IloData, IloError, RedfishClient, SshClient
from .const import (
    CONF_PROTOCOL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    PROTOCOL_REDFISH,
    PROTOCOL_SSH,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME, default="Administrator"): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def detect(hass: HomeAssistant, host: str, username: str, password: str) -> tuple[str, IloData]:
    """Prova Redfish, poi SSH. Restituisce protocollo e prima lettura."""
    redfish = RedfishClient(async_get_clientsession(hass, verify_ssl=False), host, username, password)
    try:
        if await redfish.async_probe():
            return PROTOCOL_REDFISH, await redfish.async_fetch()
    except IloAuthError:
        raise
    except IloError as err:
        _LOGGER.debug("Redfish non disponibile su %s: %s", host, err)

    ssh = SshClient(hass.async_add_executor_job, host, username, password)
    return PROTOCOL_SSH, await ssh.async_fetch()


class IloConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                protocol, data = await detect(
                    self.hass, host, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                )
            except IloAuthError:
                errors["base"] = "invalid_auth"
            except IloError as err:
                _LOGGER.warning("iLO %s non raggiungibile: %s", host, err)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Errore inatteso durante la configurazione di %s", host)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(data.serial or f"host_{host}")
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=data.name or host,
                    data={**user_input, CONF_HOST: host, CONF_PROTOCOL: protocol},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            try:
                await detect(self.hass, data[CONF_HOST], data[CONF_USERNAME], data[CONF_PASSWORD])
            except IloAuthError:
                errors["base"] = "invalid_auth"
            except IloError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return IloOptionsFlow()


class IloOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        protocol = self.config_entry.data[CONF_PROTOCOL]
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL[protocol])
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int), vol.Range(min=MIN_SCAN_INTERVAL, max=3600)
                    )
                }
            ),
        )
