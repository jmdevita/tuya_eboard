"""Constants for the Tuya E-Board (BLE) integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "tuya_eboard"

# Config entry keys (credentials stored in entry.data, never read from disk at runtime).
CONF_ADDRESS: Final = "address"
CONF_LOCAL_KEY: Final = "local_key"
CONF_DEVICE_ID: Final = "device_id"
CONF_UUID: Final = "uuid"
CONF_PRODUCT_ID: Final = "product_id"
CONF_PRODUCT_NAME: Final = "product_name"
CONF_CATEGORY: Final = "category"

# Tuya BLE v4 service advertised by these boards (matches the manifest matcher).
SERVICE_UUID_FD50: Final = "0000fd50-0000-1000-8000-00805f9b34fb"

# Poll cadence: the board is reachable only when on + remote awake (ride boundaries). We
# listen passively and connect on demand; don't reconnect more often than this.
POLL_INTERVAL_SECONDS: Final = 300.0

# Seconds to collect the proactive DP dump after connecting (passed to read_all_dps).
SETTLE_SECONDS: Final = 5.0
