"""Tuya cloud access for onboarding - list a project's devices + pull local keys.

Thin async wrapper over ``tinytuya.Cloud`` (the same client ``tools/pull_schema.py``
uses). Used only by the config flow / reauth, never in the BLE hot path. The cloud call
is blocking (``requests``), so it runs in an executor.

The user supplies Tuya IoT *project* credentials (access id + secret + region); the
local key only exists in the cloud, so a project is unavoidable - but this replaces the
manual ``tinytuya wizard`` + copy-paste with "log in, pick your board".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Tuya data-center regions accepted by tinytuya (apiRegion) -> friendly label.
REGIONS: dict[str, str] = {
    "us": "United States (Western)",
    "us-e": "United States (Eastern)",
    "eu": "Central Europe",
    "eu-w": "Western Europe",
    "cn": "China",
    "in": "India",
}


class CloudError(Exception):
    """Base class for cloud onboarding errors."""


class CloudAuthError(CloudError):
    """Bad access id/secret or wrong region (login rejected)."""


class CloudConnError(CloudError):
    """Network/transport problem reaching the Tuya cloud."""


@dataclass(frozen=True)
class CloudDevice:
    """A device as listed by the Tuya cloud (only the fields we need)."""

    id: str
    name: str
    local_key: str
    mac: str
    uuid: str
    category: str
    product_id: str


def _norm_mac(value: str) -> str:
    """Reduce a MAC/address to bare lowercase hex for comparison."""
    return "".join(re.findall(r"[0-9a-f]", (value or "").lower()))


def match_by_mac(devices: list[CloudDevice], ble_address: str) -> list[CloudDevice]:
    """Return cloud devices whose MAC matches the discovered BLE address.

    On Linux/Pi hosts the BLE address *is* the MAC, so this auto-selects the board. On
    macOS / some proxies the address is a random UUID and won't match - callers then
    fall back to letting the user pick.
    """
    target = _norm_mac(ble_address)
    if not target:
        return []
    return [d for d in devices if d.mac and _norm_mac(d.mac) == target]


def _to_device(raw: dict) -> CloudDevice:
    return CloudDevice(
        id=raw.get("id", ""),
        name=(raw.get("name") or "").strip(),
        local_key=raw.get("key", ""),
        mac=raw.get("mac", ""),
        uuid=raw.get("uuid", ""),
        category=raw.get("category", ""),
        product_id=raw.get("product_id", ""),
    )


def _list_devices_sync(
    region: str, access_id: str, access_secret: str
) -> list[CloudDevice]:
    """Blocking: construct the cloud client and list devices."""
    import tinytuya  # imported lazily; declared in manifest requirements

    try:
        cloud = tinytuya.Cloud(
            apiRegion=region, apiKey=access_id, apiSecret=access_secret
        )
    except Exception as err:  # noqa: BLE001 - network/transport building the client
        raise CloudConnError(str(err)) from err

    # The constructor performs the token login; a missing token means bad creds/region.
    if not getattr(cloud, "token", None):
        raise CloudAuthError("Tuya cloud login failed (check id/secret/region)")

    try:
        result = cloud.getdevices(verbose=False)
    except Exception as err:  # noqa: BLE001 - network/transport listing devices
        raise CloudConnError(str(err)) from err

    if isinstance(result, dict):  # tinytuya returns an error dict on failure
        raise CloudConnError(str(result.get("Payload") or result))
    if not isinstance(result, list):
        raise CloudConnError("unexpected response from Tuya cloud")
    return [_to_device(d) for d in result if isinstance(d, dict)]


async def async_list_devices(
    hass: HomeAssistant, region: str, access_id: str, access_secret: str
) -> list[CloudDevice]:
    """List the project's devices with local keys.

    Raises ``CloudAuthError`` / ``CloudConnError``.
    """
    return await hass.async_add_executor_job(
        _list_devices_sync, region, access_id, access_secret
    )
