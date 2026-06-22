"""High-level connect-on-demand API + ESC safety layer.

Wraps the vendored ``TuyaBLEDevice`` with:
  * BLE discovery that works on macOS (CoreBluetooth hides the MAC) and Linux.
  * ``read_all_dps()`` - connect, let the board dump its cached DPs, snapshot,
    disconnect.
  * ``write_dp()`` - refused unless explicitly opted out of read-only AND the DP
    is on a known-safe allowlist AND the value is in range. A motor ESC is not a
    light bulb; default is read-only.
"""

from __future__ import annotations

import asyncio
import logging

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from ._vendor.tuya_ble import SERVICE_UUID, TuyaBLEDevice, TuyaBLEDeviceCredentials
from ._vendor.tuya_ble.const import detect_generation
from .credentials import JSONDeviceManager
from .protocol import DataPoint, DataPointType, encode_value

_LOGGER = logging.getLogger(__name__)

# Passive-dump settle window: after connect+pair, the board proactively reports
# its cached DPs. Wait this long collecting notifications before snapshotting.
DEFAULT_SETTLE_SECONDS = 4.0

# Tuya BLE service UUID fragments seen in advertisements. Older devices use the
# custom 0xA201; newer ones use the SIG-assigned 0xFD50. The GATT characteristics
# used for the actual protocol are the same either way.
TUYA_SERVICE_FRAGMENTS = ("a201", "fd50")

# Safety allowlist for writes: dp_id -> (DataPointType, validator(value)->bool).
# EMPTY until the DP map is discovered & confirmed via the app oracle (§5 Ph.2).
# While empty, every write is refused - which is the correct default.
WRITE_ALLOWLIST: dict[int, tuple[DataPointType, "object"]] = {}


def _matches(creds: TuyaBLEDeviceCredentials, dev: BLEDevice, adv: AdvertisementData) -> bool:
    """Is this advertisement our board?

    Linux/BlueZ exposes the real MAC as ``dev.address``; macOS does not, so we
    fall back to matching the Tuya service UUID plus (when present) the product
    id embedded in the service data.
    """
    # Name heuristic: many boards advertise a short name (often a model number)
    # that is a substring of the cloud product_name.
    name = (dev.name or "").strip()
    product_name = (creds.product_name or "")
    if name and product_name and name.lower() in product_name.lower():
        return True

    # Service UUID: accept either Tuya service (0xA201 legacy or 0xFD50 newer).
    uuids = [u.lower() for u in (adv.service_uuids or [])]
    if not any(frag in u for u in uuids for frag in TUYA_SERVICE_FRAGMENTS):
        return False
    # If 0xA201 service_data carries the product id (leading 0x00 marker), verify.
    sd = (adv.service_data or {}).get(SERVICE_UUID)
    if sd and len(sd) > 1 and sd[0] == 0x00:
        return sd[1:].decode(errors="ignore").strip("\x00") == creds.product_id
    # Otherwise accept the Tuya advertiser (fine when only one board is near).
    return True


async def discover_board(
    creds: TuyaBLEDeviceCredentials,
    mac: str | None = None,
    timeout: float = 15.0,
) -> tuple[BLEDevice, AdvertisementData]:
    """Scan for the board and return its BLEDevice + advertisement data.

    ``mac`` (from devices.json) is used directly on platforms that expose it;
    otherwise we match by Tuya service UUID / product id.
    """
    found: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def _cb(dev: BLEDevice, adv: AdvertisementData) -> None:
        if mac and dev.address.upper() == mac.upper():
            found[dev.address] = (dev, adv)
        elif _matches(creds, dev, adv):
            found.setdefault(dev.address, (dev, adv))

    scanner = BleakScanner(detection_callback=_cb)
    await scanner.start()
    try:
        deadline = timeout
        while deadline > 0 and not found:
            await asyncio.sleep(0.5)
            deadline -= 0.5
    finally:
        await scanner.stop()

    if not found:
        raise TimeoutError(
            "Board not found. Powered on and in range? On macOS the MAC is "
            "hidden, so matching falls back to the 0xA201 service UUID."
        )
    # Prefer a MAC match if present, else the strongest signal.
    if mac and mac.upper() in {a.upper() for a in found}:
        key = next(a for a in found if a.upper() == mac.upper())
        return found[key]
    return max(found.values(), key=lambda da: da[1].rssi or -999)


class TuyaEboardDevice:
    """Connect-on-demand wrapper around the vendored TuyaBLEDevice."""

    def __init__(
        self,
        creds: TuyaBLEDeviceCredentials,
        ble_device: BLEDevice,
        adv: AdvertisementData | None = None,
        *,
        read_only: bool = True,
    ) -> None:
        self._creds = creds
        self._manager = JSONDeviceManager(creds)
        self._inner = TuyaBLEDevice(self._manager, ble_device, adv)
        # Select the protocol generation (GATT chars + device-info payload) from
        # the advertised service: 0xFD50 -> v4 (verified), 0xA201 -> v3 (beta).
        self._generation = detect_generation(adv.service_uuids if adv else None)
        self._inner.set_generation(self._generation)
        if self._generation.status == "beta":
            _LOGGER.warning(
                "Using BETA protocol generation %s (untested) for %s",
                self._generation.name, getattr(ble_device, "address", "?"),
            )
        self.read_only = read_only

    @property
    def generation(self):
        return self._generation

    @classmethod
    async def discover_and_create(
        cls,
        creds: TuyaBLEDeviceCredentials,
        mac: str | None = None,
        *,
        read_only: bool = True,
        timeout: float = 15.0,
    ) -> "TuyaEboardDevice":
        ble_device, adv = await discover_board(creds, mac=mac, timeout=timeout)
        return cls(creds, ble_device, adv, read_only=read_only)

    @property
    def inner(self) -> TuyaBLEDevice:
        return self._inner

    def _snapshot(self) -> list[DataPoint]:
        """Convert the vendored datapoint cache into our pure DataPoint list."""
        dps: list[DataPoint] = []
        store = self._inner.datapoints
        for dp_id in sorted(store._datapoints):  # noqa: SLF001 - read-only access
            v = store[dp_id]
            raw = v._get_value()  # noqa: SLF001 - exact wire bytes
            dps.append(
                DataPoint(
                    id=v.id,
                    type=DataPointType(v.type.value),
                    raw=raw,
                    value=v.value,
                )
            )
        return dps

    async def read_all_dps(
        self, settle: float = DEFAULT_SETTLE_SECONDS
    ) -> list[DataPoint]:
        """Connect, request status, collect the proactive DP dump, disconnect."""
        await self._inner.initialize()
        await self._inner.update()  # triggers handshake + status request
        await asyncio.sleep(settle)  # let proactive DP reports land
        try:
            return self._snapshot()
        finally:
            await self._inner.stop()

    async def write_dp(self, dp_id: int, value: object) -> None:
        """Write a config DP - guarded by several independent gates."""
        if self.read_only:
            raise PermissionError(
                "Device is read-only. Construct with read_only=False to enable "
                "writes (only after the DP is confirmed via the app oracle)."
            )
        # The vendored protocol only implements DP *sending* for v3, and even that
        # uses a 1-byte length (wrong for v4's 2-byte format). So writes are not
        # actually functional on v4 yet - fail clearly rather than emit a malformed
        # frame to a motor controller or surface a cryptic TuyaBLEDeviceError.
        if self._generation.name == "v4":
            raise NotImplementedError(
                "DP writes are not implemented for Tuya BLE v4 (receive-only). "
                "v4 DP sending (2-byte length, FUN_SENDER_DPS_V4) must be added "
                "and hardware-verified before any write path is enabled."
            )
        if dp_id not in WRITE_ALLOWLIST:
            raise PermissionError(
                f"DP {dp_id} is not on the write allowlist. Refusing to write an "
                "unverified datapoint to a motor controller."
            )
        dp_type, validator = WRITE_ALLOWLIST[dp_id]
        if not validator(value):  # type: ignore[operator]
            raise ValueError(f"Value {value!r} out of safe range for DP {dp_id}.")
        dp = self._inner.datapoints.get_or_create(dp_id, _vendor_type(dp_type))
        await dp.set_value(encode_value(dp_type, value))

    async def stop(self) -> None:
        await self._inner.stop()


def _vendor_type(t: DataPointType):
    """Map our DataPointType to the vendored TuyaBLEDataPointType."""
    from ._vendor.tuya_ble import TuyaBLEDataPointType

    return TuyaBLEDataPointType(int(t))
