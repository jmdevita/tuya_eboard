from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

GATT_MTU = 20

DEFAULT_ATTEMPTS = 0xFFFF

# LOCAL MOD: Tuya BLE protocol generations differ in (a) the advertised GATT
# service + write/notify characteristics and (b) the device-info handshake
# payload. We select these per-device from the advertised service UUID. (DP
# framing differences are handled in the command handler + protocol codec, not
# here.)  v4 (0xFD50) is verified against the HW7009/OMW Hussar; v3 (0xA201) is
# the classic ha_tuya_ble target — supported in code but UNVERIFIED (beta).


@dataclass(frozen=True)
class Generation:
    name: str
    service_uuid: str
    char_notify: str
    char_write: str
    device_info_payload: bytes
    status: str  # "stable" (verified) | "beta" (untested)


GEN_V3 = Generation(
    name="v2/v3",
    service_uuid="0000a201-0000-1000-8000-00805f9b34fb",
    char_notify="00002b10-0000-1000-8000-00805f9b34fb",
    char_write="00002b11-0000-1000-8000-00805f9b34fb",
    device_info_payload=b"",          # v3: empty device-info request
    status="beta",
)
GEN_V4 = Generation(
    name="v4",
    service_uuid="0000fd50-0000-1000-8000-00805f9b34fb",
    char_notify="00000002-0000-1001-8001-00805f9b07d0",
    char_write="00000001-0000-1001-8001-00805f9b07d0",
    device_info_payload=bytes([0x00, 0xF3]),  # v4: required, else the board drops
    status="stable",
)

GENERATIONS = (GEN_V4, GEN_V3)
DEFAULT_GENERATION = GEN_V4


def detect_generation(service_uuids) -> Generation:
    """Pick the protocol generation from advertised service UUIDs (default v4)."""
    uuids = [str(u).lower() for u in (service_uuids or [])]
    for gen in GENERATIONS:
        frag = gen.service_uuid[4:8]  # 16-bit part, e.g. 'fd50' / 'a201'
        if any(frag in u for u in uuids):
            return gen
    return DEFAULT_GENERATION


# Back-compat module constants default to the verified (v4) generation.
CHARACTERISTIC_NOTIFY = GEN_V4.char_notify
CHARACTERISTIC_WRITE = GEN_V4.char_write
SERVICE_UUID = GEN_V4.service_uuid

MANUFACTURER_DATA_ID = 0x07D0

RESPONSE_WAIT_TIMEOUT = 60


class TuyaBLECode(Enum):
    FUN_SENDER_DEVICE_INFO = 0x0000
    FUN_SENDER_PAIR = 0x0001
    FUN_SENDER_DPS = 0x0002
    FUN_SENDER_DEVICE_STATUS = 0x0003

    FUN_SENDER_UNBIND = 0x0005
    FUN_SENDER_DEVICE_RESET = 0x0006

    FUN_SENDER_OTA_START = 0x000C
    FUN_SENDER_OTA_FILE = 0x000D
    FUN_SENDER_OTA_OFFSET = 0x000E
    FUN_SENDER_OTA_UPGRADE = 0x000F
    FUN_SENDER_OTA_OVER = 0x0010

    FUN_SENDER_DPS_V4 = 0x0027

    FUN_RECEIVE_DP = 0x8001
    FUN_RECEIVE_TIME_DP = 0x8003
    FUN_RECEIVE_SIGN_DP = 0x8004
    FUN_RECEIVE_SIGN_TIME_DP = 0x8005

    FUN_RECEIVE_DP_V4 = 0x8006
    FUN_RECEIVE_TIME_DP_V4 = 0x8007

    FUN_RECEIVE_TIME1_REQ = 0x8011
    FUN_RECEIVE_TIME2_REQ = 0x8012


class TuyaBLEDataPointType(Enum):
    DT_RAW = 0
    DT_BOOL = 1
    DT_VALUE = 2
    DT_STRING = 3
    DT_ENUM = 4
    DT_BITMAP = 5
