"""Coordinator: una lettura dell'iLO per tutte le entità del server."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import IloAuthError, IloData, IloError, RedfishClient, SshClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Dopo un comando di alimentazione rileggo lo stato più spesso per un po'
_FOLLOW_UP_DELAYS = (5, 20, 60)


class IloCoordinator(DataUpdateCoordinator[IloData]):
    """Aggiorna periodicamente i dati di un iLO."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: RedfishClient | SshClient,
        scan_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._follow_up: asyncio.Task | None = None

    async def _async_update_data(self) -> IloData:
        try:
            return await self.client.async_fetch()
        except IloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except IloError as err:
            raise UpdateFailed(str(err)) from err

    async def async_power(self, action: str) -> None:
        """Invia un comando di alimentazione e segue il cambio di stato."""
        try:
            await self.client.async_power(action)
        except IloAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except IloError as err:
            raise HomeAssistantError(f"iLO {self.config_entry.title}: {err}") from err

        if self._follow_up and not self._follow_up.done():
            self._follow_up.cancel()
        self._follow_up = self.config_entry.async_create_background_task(
            self.hass, self._async_follow_up(), f"{DOMAIN}_follow_up"
        )

    async def _async_follow_up(self) -> None:
        for delay in _FOLLOW_UP_DELAYS:
            await asyncio.sleep(delay)
            await self.async_request_refresh()
