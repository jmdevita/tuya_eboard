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

# Tuya cloud (project) credentials - stored so reauth can re-pull a rotated local_key.
CONF_ACCESS_ID: Final = "access_id"
CONF_ACCESS_SECRET: Final = "access_secret"
CONF_REGION: Final = "region"

# Tuya BLE v4 service advertised by these boards (matches the manifest matcher).
SERVICE_UUID_FD50: Final = "0000fd50-0000-1000-8000-00805f9b34fb"

# Fired when the odometer advances between two reads (a completed ride). The event
# carries the ride delta so user-space blueprints/automations can journal it without
# re-deriving anything. See blueprints/automation/ride_journal.yaml.
EVENT_RIDE_COMPLETED: Final = "tuya_eboard_ride_completed"

# DP ids used for ride derivation (kept in sync with sensor.py value_fns).
DP_BATTERY: Final = 3  # battery_percentage (%)
DP_TRIP_DISTANCE: Final = 5  # mileage_once (km x10, per-trip; reset/wiped on sleep)
DP_ODOMETER: Final = 12  # mileage_total (km x10, cumulative)
DP_VOLTAGE: Final = 20  # voltage_current (V x10)

# Poll cadence: the board is reachable only when on + remote awake (ride boundaries). We
# listen passively and connect on demand; don't reconnect more often than this.
POLL_INTERVAL_SECONDS: Final = 300.0

# Seconds to collect the proactive DP dump after connecting (passed to read_all_dps).
SETTLE_SECONDS: Final = 5.0

# Presence: an awake board advertises many times/sec, so if we haven't heard it within
# this window it's asleep/out of range. (HA's own unavailable tracking is far laggier,
# which is why `present` tracks advertisements directly.)
PRESENCE_TIMEOUT_SECONDS: Final = 90.0
# How often to re-evaluate presence so `present` flips off without a new advertisement.
PRESENCE_CHECK_SECONDS: Final = 30.0
