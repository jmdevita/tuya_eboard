"""Load device credentials from tinytuya's ``devices.json``.

The vendored ``TuyaBLEDevice`` pulls its credentials through an
``AbstaractTuyaBLEDeviceManager``. We implement a tiny manager that serves the
cached key from ``devices.json`` so nothing here ever touches the Tuya cloud at
runtime - the cloud was only needed once, to fetch the local key.
"""

from __future__ import annotations

import json
from pathlib import Path

from ._vendor.tuya_ble import (
    AbstaractTuyaBLEDeviceManager,
    TuyaBLEDeviceCredentials,
)

DEFAULT_DEVICES_JSON = Path(__file__).resolve().parent.parent / "devices.json"


class StaleKeyError(RuntimeError):
    """Raised when the local key looks missing/empty.

    A *stale* key (one that fails the BLE handshake) usually means the board was
    re-paired in the Tuya app, which rotates the local key. Re-run
    ``python -m tinytuya wizard`` to refresh ``devices.json``.
    """


def _entry_to_credentials(entry: dict) -> TuyaBLEDeviceCredentials:
    """Map a tinytuya devices.json entry to TuyaBLEDeviceCredentials."""
    local_key = entry.get("key") or ""
    if not local_key:
        raise StaleKeyError(
            f"No local key for device {entry.get('id')!r} in devices.json. "
            "Re-run `python -m tinytuya wizard`."
        )
    return TuyaBLEDeviceCredentials(
        uuid=entry.get("uuid", ""),
        local_key=local_key,
        device_id=entry.get("id", ""),
        category=entry.get("category", ""),
        product_id=entry.get("product_id", ""),
        device_name=entry.get("name"),
        product_model=entry.get("model") or None,
        product_name=(entry.get("product_name") or "").strip() or None,
    )


def load_credentials(
    device_id: str | None = None,
    path: str | Path = DEFAULT_DEVICES_JSON,
) -> TuyaBLEDeviceCredentials:
    """Load credentials for ``device_id`` (or the only device) from devices.json."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run `python -m tinytuya wizard` first."
        )
    devices = json.loads(path.read_text())
    if not devices:
        raise ValueError(f"{path} contains no devices.")

    if device_id is None:
        if len(devices) > 1:
            ids = ", ".join(d.get("id", "?") for d in devices)
            raise ValueError(
                f"Multiple devices in {path}; pass device_id explicitly: {ids}"
            )
        entry = devices[0]
    else:
        entry = next((d for d in devices if d.get("id") == device_id), None)
        if entry is None:
            raise KeyError(f"device_id {device_id!r} not found in {path}")

    return _entry_to_credentials(entry)


class JSONDeviceManager(AbstaractTuyaBLEDeviceManager):
    """Serves cached credentials to the vendored TuyaBLEDevice.

    ``TuyaBLEDevice`` looks credentials up by BLE address, but on macOS the
    address is a random CoreBluetooth UUID rather than the MAC - so we ignore
    the address and just return the single cached credential set.
    """

    def __init__(self, credentials: TuyaBLEDeviceCredentials) -> None:
        self._credentials = credentials

    @property
    def credentials(self) -> TuyaBLEDeviceCredentials:
        return self._credentials

    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        return self._credentials
