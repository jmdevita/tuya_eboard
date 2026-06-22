"""The Tuya E-Board (BLE) integration."""

from __future__ import annotations

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS
from .coordinator import TuyaEboardCoordinator
from .data import TuyaEboardConfigEntry, build_credentials

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: TuyaEboardConfigEntry
) -> bool:
    """Set up Tuya E-Board from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    credentials = build_credentials(entry.data)

    coordinator = TuyaEboardCoordinator(hass, _LOGGER, address, credentials)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Start listening for advertisements only after platforms have subscribed, so the
    # first poll's snapshot reaches the entities.
    entry.async_on_unload(coordinator.async_start())
    # The coordinator runs a self-rescheduling presence check (only while the board is
    # around); make sure any pending one is cancelled on unload.
    entry.async_on_unload(coordinator.async_stop_presence_tracking)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: TuyaEboardConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
