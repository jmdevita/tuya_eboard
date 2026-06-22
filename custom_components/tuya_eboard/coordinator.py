"""Advertisement-triggered, connect-on-demand coordinator for the e-board.

The board (an ESC) is only reachable over BLE when it's powered on and the remote is
awake — the two ends of a ride. We therefore do NOT poll in a loop: HA's passive scanner
notices the board advertise, ``_needs_poll`` gates a connect, and ``_async_update``
the existing ``TuyaEboardDevice.read_all_dps()`` snapshot (connect → handshake → dump →
disconnect). Between reads the last snapshot persists with a ``last_seen`` timestamp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.util import dt as dt_util

from .const import POLL_INTERVAL_SECONDS, SETTLE_SECONDS
from .tuya_eboard_ble._vendor.tuya_ble import TuyaBLEDeviceCredentials
from .tuya_eboard_ble.device import TuyaEboardDevice
from .tuya_eboard_ble.protocol import DataPoint


@dataclass
class EboardSnapshot:
    """One read of the board, kept as last-known state between polls."""

    dps: dict[int, DataPoint]
    last_seen: datetime


class TuyaEboardCoordinator(ActiveBluetoothDataUpdateCoordinator[EboardSnapshot]):
    """Connect-on-demand snapshot coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        address: str,
        credentials: TuyaBLEDeviceCredentials,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=logger,
            address=address,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_update,
            mode=BluetoothScanningMode.PASSIVE,
            connectable=True,
        )
        self._credentials = credentials

    def _needs_poll(
        self,
        service_info: BluetoothServiceInfoBleak,
        seconds_since_last_poll: float | None,
    ) -> bool:
        # Connect only if HA is up, it's been long enough since the last read, and an
        # adapter that can actually connect to the board is in range.
        return (
            self.hass.state is CoreState.running
            and (
                seconds_since_last_poll is None
                or seconds_since_last_poll > POLL_INTERVAL_SECONDS
            )
            and bool(
                bluetooth.async_ble_device_from_address(
                    self.hass, service_info.device.address, connectable=True
                )
            )
        )

    async def _async_update(
        self, service_info: BluetoothServiceInfoBleak
    ) -> EboardSnapshot:
        """Poll: connect, snapshot all DPs, disconnect. Return value -> self.data."""
        device = TuyaEboardDevice(
            self._credentials,
            service_info.device,
            service_info.advertisement,
            read_only=True,
        )
        dps = await device.read_all_dps(settle=SETTLE_SECONDS)
        if not dps:
            # Empty read -> raise so the coordinator keeps the previous snapshot and
            # marks the poll unsuccessful, rather than blanking every entity.
            raise ValueError("board reported no datapoints")
        return EboardSnapshot(
            dps={dp.id: dp for dp in dps},
            last_seen=dt_util.utcnow(),
        )
