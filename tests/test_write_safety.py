"""Write-safety regression tests - no hardware, no BLE I/O.

These guard the invariants that protect a motor controller from bad writes. They
must never silently regress:
  * read-only (the default) refuses writes
  * v4 DP writes raise NotImplementedError BEFORE any frame is built (the vendored
    send path is v3-only; v4 sending isn't implemented)
  * the v4 guard fires regardless of the allowlist
  * on v3 (where sending exists), the empty allowlist is the gate
  * generation is detected from the advertised service

All guards raise before `set_value()` would open a connection, so no BLE is hit.
"""

import asyncio

import pytest

from tuya_eboard_ble._vendor.tuya_ble import TuyaBLEDeviceCredentials
from tuya_eboard_ble.device import TuyaEboardDevice

FD50 = "0000fd50-0000-1000-8000-00805f9b34fb"  # v4
A201 = "0000a201-0000-1000-8000-00805f9b34fb"  # v3


class _FakeBLE:
    address = "AA:BB:CC:DD:EE:FF"
    name = "7009"


class _Adv:
    def __init__(self, service: str) -> None:
        self.service_uuids = [service]


def _device(service: str = FD50, read_only: bool = True) -> TuyaEboardDevice:
    creds = TuyaBLEDeviceCredentials("u", "k", "id", "cat", "pid", "n", "m", "pn")
    return TuyaEboardDevice(creds, _FakeBLE(), _Adv(service), read_only=read_only)


def test_read_only_refuses_writes():
    with pytest.raises(PermissionError):
        asyncio.run(_device(read_only=True).write_dp(108, 50))


def test_v4_write_not_implemented():
    # read-only off, but the v4 send path is unimplemented -> must raise, not connect
    with pytest.raises(NotImplementedError):
        asyncio.run(_device(FD50, read_only=False).write_dp(108, 50))


def test_v4_guard_fires_before_allowlist():
    # a DP that's NOT on the allowlist must still hit the v4 guard first
    with pytest.raises(NotImplementedError):
        asyncio.run(_device(FD50, read_only=False).write_dp(999, 0))


def test_v3_write_blocked_by_empty_allowlist():
    # v3 sending exists, so the guard becomes the (empty) allowlist
    with pytest.raises(PermissionError):
        asyncio.run(_device(A201, read_only=False).write_dp(108, 50))


def test_generation_detected_from_advert():
    assert _device(FD50).generation.name == "v4"
    assert _device(A201).generation.name == "v2/v3"
