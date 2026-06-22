"""tuya_eboard_ble - a board-agnostic Tuya BLE client for e-board ESCs.

Snapshot+delta model: connect-on-demand, read DPs, disconnect. The Tuya BLE
crypto/handshake is borrowed verbatim from PlusPlus-ua/ha_tuya_ble (vendored
under ``_vendor/tuya_ble``); the genuinely new work lives in ``protocol`` (a
pure, testable DP codec) and ``device`` (the high-level API + safety layer).
Per-product datapoint meaning lives as data in ``dpmaps/<product_id>.yaml``.
"""

from .credentials import JSONDeviceManager, load_credentials
from .device import TuyaEboardDevice, discover_board

__all__ = [
    "JSONDeviceManager",
    "load_credentials",
    "TuyaEboardDevice",
    "discover_board",
]
