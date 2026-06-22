"""Config flow for Tuya E-Board (BLE).

v1 acquires the Tuya ``local_key`` manually (prefilled from a local ``devices.json``
if one happens to be present). The entered credentials are verified by performing one
real connect+read before the entry is created, so a bad key fails fast. Cloud-login
credential refresh is a planned follow-up (see the plan / design doc).
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import (
    CONF_ADDRESS,
    CONF_CATEGORY,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    CONF_UUID,
    DOMAIN,
    SERVICE_UUID_FD50,
    SETTLE_SECONDS,
)
from .data import build_credentials
from .tuya_eboard_ble.device import TuyaEboardDevice

_LOGGER = logging.getLogger(__name__)


def _prefill() -> dict[str, str]:
    """Best-effort defaults from a local devices.json (dev only; absent in HA)."""
    try:
        from .tuya_eboard_ble.credentials import load_credentials

        creds = load_credentials()
    except Exception:  # noqa: BLE001 — no devices.json in a normal install; that's fine
        return {}
    return {
        CONF_LOCAL_KEY: creds.local_key or "",
        CONF_DEVICE_ID: creds.device_id or "",
        CONF_UUID: creds.uuid or "",
        CONF_PRODUCT_ID: creds.product_id or "",
    }


class TuyaEboardConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya E-Board (BLE)."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: BluetoothServiceInfoBleak | None = None
        self._discovered: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a board discovered by the bluetooth integration (0xFD50)."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "Tuya E-Board"
        }
        return await self.async_step_credentials()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual add: prompt to power the board on, then scan on demand.

        The board auto-sleeps when idle, so we don't scan immediately (that almost
        always finds nothing and dead-ends). Instead we show a 'Start scan' button so
        the user can wake the board first.
        """
        return self.async_show_menu(step_id="user", menu_options=["scan"])

    async def async_step_scan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Scan for advertising boards; re-prompt (no dead-end) if none are found."""
        # Distinguish "no Bluetooth adapter at all" from "board not found" — they need
        # different advice (add an adapter/proxy vs. wake the board).
        if bluetooth.async_scanner_count(self.hass, connectable=True) == 0:
            return self.async_show_menu(
                step_id="no_bluetooth", menu_options=["scan"]
            )
        self._discovered = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(
                self.hass, connectable=True
            )
            if SERVICE_UUID_FD50 in info.service_uuids
            and info.address not in self._async_current_ids()
        }
        if not self._discovered:
            return self.async_show_menu(step_id="no_devices", menu_options=["scan"])
        return await self.async_step_pick()

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one of the discovered boards, then enter credentials."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovery = self._discovered.get(address)
            return await self.async_step_credentials()

        return self.async_show_form(
            step_id="pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {
                            addr: f"{info.name or 'Tuya E-Board'} ({addr})"
                            for addr, info in self._discovered.items()
                        }
                    )
                }
            ),
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect + verify the Tuya credentials for the chosen board."""
        assert self._discovery is not None
        errors: dict[str, str] = {}

        if user_input is not None:
            data = {
                CONF_ADDRESS: self._discovery.address,
                CONF_PRODUCT_NAME: self._discovery.name or "",
                CONF_CATEGORY: "",
                **user_input,
            }
            error = await self._async_try_read(data)
            if error is None:
                return self.async_create_entry(
                    title=self._discovery.name or "Tuya E-Board",
                    data=data,
                )
            errors["base"] = error

        pre = _prefill()
        return self.async_show_form(
            step_id="credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_LOCAL_KEY, default=pre.get(CONF_LOCAL_KEY, "")
                    ): str,
                    vol.Required(
                        CONF_DEVICE_ID, default=pre.get(CONF_DEVICE_ID, "")
                    ): str,
                    vol.Required(CONF_UUID, default=pre.get(CONF_UUID, "")): str,
                    vol.Optional(
                        CONF_PRODUCT_ID, default=pre.get(CONF_PRODUCT_ID, "")
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._discovery.name or "Tuya E-Board"
            },
        )

    async def _async_try_read(self, data: dict[str, Any]) -> str | None:
        """Return an error key, or None if a real connect+read succeeds."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, data[CONF_ADDRESS], connectable=True
        )
        if ble_device is None:
            return "cannot_connect"  # board asleep / out of range right now
        device = TuyaEboardDevice(
            build_credentials(data),
            ble_device,
            self._discovery.advertisement if self._discovery else None,
            read_only=True,
        )
        try:
            dps = await device.read_all_dps(settle=SETTLE_SECONDS)
        except Exception:  # noqa: BLE001 — handshake/transport errors -> bad key or link
            _LOGGER.debug("Validation read failed", exc_info=True)
            return "invalid_auth"
        if not dps:
            return "cannot_connect"
        return None
