"""Config flow for Tuya E-Board (BLE).

Two ways to get the Tuya ``local_key`` for a board:
  * **Cloud login** (default) - enter Tuya IoT project creds; we list the project's
    devices and pull the key automatically, matching the board by MAC.
  * **Manual** (advanced) - paste local_key / device_id / uuid.

Either way the credentials are verified by one real connect+read before the entry is
created. Stored cloud creds also power the reauth flow when a key rotates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .cloud import (
    REGIONS,
    CloudAuthError,
    CloudConnError,
    CloudDevice,
    async_list_devices,
    match_by_mac,
)
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_ADDRESS,
    CONF_CATEGORY,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    CONF_REGION,
    CONF_UUID,
    DOMAIN,
    SERVICE_UUID_FD50,
    SETTLE_SECONDS,
)
from .data import build_credentials
from .tuya_eboard_ble.device import TuyaEboardDevice

_LOGGER = logging.getLogger(__name__)

# Linked from the cloud-login step (HA requires URLs via description_placeholders,
# not inline in strings.json). Points at the official Tuya project-setup walkthrough.
TUYA_DOCS_URL = "https://www.home-assistant.io/integrations/tuya/"


def _prefill() -> dict[str, str]:
    """Best-effort defaults from a local devices.json (dev only; absent in HA)."""
    try:
        from .tuya_eboard_ble.credentials import load_credentials

        creds = load_credentials()
    except Exception:  # noqa: BLE001 - no devices.json in a normal install; that's fine
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
        self._cloud_creds: dict[str, str] = {}
        self._cloud_devices: list[CloudDevice] = []

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
        return await self.async_step_choose_auth()

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
        # Distinguish "no Bluetooth adapter at all" from "board not found" - they need
        # different advice (add an adapter/proxy vs. wake the board). Each re-prompt is
        # its own step (a shown menu's step_id must have a matching handler method).
        if bluetooth.async_scanner_count(self.hass, connectable=True) == 0:
            return await self.async_step_no_bluetooth()
        self._discovered = {
            info.address: info
            for info in bluetooth.async_discovered_service_info(
                self.hass, connectable=True
            )
            if SERVICE_UUID_FD50 in info.service_uuids
            and info.address not in self._async_current_ids()
        }
        if not self._discovered:
            return await self.async_step_no_devices()
        return await self.async_step_pick()

    async def async_step_no_bluetooth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No Bluetooth adapter available - let the user fix it and rescan."""
        return self.async_show_menu(step_id="no_bluetooth", menu_options=["scan"])

    async def async_step_no_devices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No board advertising - let the user wake it and rescan."""
        return self.async_show_menu(step_id="no_devices", menu_options=["scan"])

    async def async_step_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick one of the discovered boards, then enter credentials."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._discovery = self._discovered.get(address)
            return await self.async_step_choose_auth()

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

    async def async_step_choose_auth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose how to provide the local key: cloud login or manual entry."""
        return self.async_show_menu(
            step_id="choose_auth", menu_options=["cloud", "credentials"]
        )

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Log into the Tuya cloud, list devices, and match the board by MAC."""
        assert self._discovery is not None
        if user_input is not None:
            self._cloud_creds = {
                CONF_ACCESS_ID: user_input[CONF_ACCESS_ID],
                CONF_ACCESS_SECRET: user_input[CONF_ACCESS_SECRET],
                CONF_REGION: user_input[CONF_REGION],
            }
            try:
                devices = await async_list_devices(
                    self.hass,
                    user_input[CONF_REGION],
                    user_input[CONF_ACCESS_ID],
                    user_input[CONF_ACCESS_SECRET],
                )
            except CloudAuthError:
                return self._cloud_form({"base": "invalid_cloud_auth"})
            except CloudConnError:
                return self._cloud_form({"base": "cloud_cannot_connect"})
            if not devices:
                return self._cloud_form({"base": "cloud_no_devices"})
            self._cloud_devices = devices
            matches = match_by_mac(devices, self._discovery.address)
            if len(matches) == 1:
                return await self._async_create_from_cloud(matches[0])
            return await self.async_step_cloud_pick()
        return self._cloud_form()

    def _cloud_form(self, errors: dict[str, str] | None = None) -> ConfigFlowResult:
        pre = self._cloud_creds
        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCESS_ID, default=pre.get(CONF_ACCESS_ID, "")
                    ): str,
                    vol.Required(
                        CONF_ACCESS_SECRET, default=pre.get(CONF_ACCESS_SECRET, "")
                    ): str,
                    vol.Required(
                        CONF_REGION, default=pre.get(CONF_REGION, "us")
                    ): vol.In(REGIONS),
                }
            ),
            errors=errors or {},
            description_placeholders={"docs_url": TUYA_DOCS_URL},
        )

    async def async_step_cloud_pick(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the board from the cloud device list (MAC auto-match didn't resolve)."""
        if user_input is not None:
            device = next(
                d for d in self._cloud_devices if d.id == user_input[CONF_DEVICE_ID]
            )
            return await self._async_create_from_cloud(device)
        return self.async_show_form(
            step_id="cloud_pick",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_ID): vol.In(
                        {
                            d.id: f"{d.name or d.product_id or 'device'} ({d.id})"
                            for d in self._cloud_devices
                        }
                    )
                }
            ),
        )

    async def _async_create_from_cloud(
        self, device: CloudDevice
    ) -> ConfigFlowResult:
        """Build creds from a cloud device, verify over BLE, and create the entry."""
        assert self._discovery is not None
        data = {
            CONF_ADDRESS: self._discovery.address,
            CONF_LOCAL_KEY: device.local_key,
            CONF_DEVICE_ID: device.id,
            CONF_UUID: device.uuid,
            CONF_PRODUCT_ID: device.product_id,
            CONF_CATEGORY: device.category,
            CONF_PRODUCT_NAME: device.name or self._discovery.name or "",
            **self._cloud_creds,
        }
        # The cloud key is authoritative (we matched the board by MAC), so only block on
        # a real key rejection. If the board is merely asleep / out of range now
        # ("cannot_connect"), create the entry anyway - the coordinator reads it when it
        # next wakes. (Manual entry stays strict, since a typo'd key must be caught.)
        if await self._async_try_read(data) == "invalid_auth":
            return self._cloud_form({"base": "invalid_auth"})
        return self.async_create_entry(
            title=device.name or self._discovery.name or "Tuya E-Board", data=data
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect + verify the Tuya credentials for the chosen board (manual)."""
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

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Triggered when the stored local key stops working (likely a re-pair)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-pull the local key from the Tuya cloud (silent if creds still valid)."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud = {
                CONF_ACCESS_ID: user_input[CONF_ACCESS_ID],
                CONF_ACCESS_SECRET: user_input[CONF_ACCESS_SECRET],
                CONF_REGION: user_input[CONF_REGION],
            }
        else:
            cloud = {
                k: entry.data.get(k, "")
                for k in (CONF_ACCESS_ID, CONF_ACCESS_SECRET, CONF_REGION)
            }

        if all(cloud.values()):
            try:
                devices = await async_list_devices(
                    self.hass,
                    cloud[CONF_REGION],
                    cloud[CONF_ACCESS_ID],
                    cloud[CONF_ACCESS_SECRET],
                )
            except CloudAuthError:
                errors["base"] = "invalid_cloud_auth"
            except CloudConnError:
                errors["base"] = "cloud_cannot_connect"
            else:
                device = next(
                    (d for d in devices if d.id == entry.data.get(CONF_DEVICE_ID)),
                    None,
                )
                if device is None:
                    errors["base"] = "cloud_no_devices"
                elif device.local_key == entry.data.get(CONF_LOCAL_KEY):
                    # Cloud key == current key, so refreshing won't fix the failure -
                    # surface it instead of silently reload-looping.
                    errors["base"] = "key_unchanged"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data={**entry.data, CONF_LOCAL_KEY: device.local_key, **cloud},
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ACCESS_ID, default=cloud.get(CONF_ACCESS_ID, "")
                    ): str,
                    vol.Required(
                        CONF_ACCESS_SECRET, default=cloud.get(CONF_ACCESS_SECRET, "")
                    ): str,
                    vol.Required(
                        CONF_REGION, default=cloud.get(CONF_REGION) or "us"
                    ): vol.In(REGIONS),
                }
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
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
        except Exception:  # noqa: BLE001 - handshake/transport errors -> bad key or link
            _LOGGER.debug("Validation read failed", exc_info=True)
            return "invalid_auth"
        if not dps:
            return "cannot_connect"
        return None
