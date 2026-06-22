"""Runtime data + credential mapping for the config entry.

Mirrors the integration_blueprint convention: the typed ``ConfigEntry`` alias lives
here (not in ``__init__``) so platforms import it without reaching the package root.
"""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_CATEGORY,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_NAME,
    CONF_UUID,
)
from .coordinator import TuyaEboardCoordinator
from .tuya_eboard_ble._vendor.tuya_ble import TuyaBLEDeviceCredentials

type TuyaEboardConfigEntry = ConfigEntry[TuyaEboardCoordinator]


def build_credentials(data: Mapping[str, str]) -> TuyaBLEDeviceCredentials:
    """Map entry.data -> TuyaBLEDeviceCredentials (the handshake needs local_key)."""
    return TuyaBLEDeviceCredentials(
        uuid=data.get(CONF_UUID, ""),
        local_key=data.get(CONF_LOCAL_KEY, ""),
        device_id=data.get(CONF_DEVICE_ID, ""),
        category=data.get(CONF_CATEGORY, ""),
        product_id=data.get(CONF_PRODUCT_ID, ""),
        device_name=data.get(CONF_PRODUCT_NAME) or None,
        product_model=None,
        product_name=data.get(CONF_PRODUCT_NAME) or None,
    )
