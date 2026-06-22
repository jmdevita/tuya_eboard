"""Advertisement-triggered, connect-on-demand coordinator for the e-board.

The board (an ESC) is only reachable over BLE when it's powered on and the remote is
awake — the two ends of a ride. We therefore do NOT poll in a loop: HA's passive scanner
notices the board advertise, ``_needs_poll`` gates a connect, and ``_async_update`` runs
the existing ``TuyaEboardDevice.read_all_dps()`` snapshot (connect → handshake → dump →
disconnect). Between reads the last snapshot persists with a ``last_seen`` timestamp.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    POLL_INTERVAL_SECONDS,
    PRESENCE_CHECK_SECONDS,
    PRESENCE_TIMEOUT_SECONDS,
    SETTLE_SECONDS,
)
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
        self._last_advert: datetime | None = None
        self._present_unsub: CALLBACK_TYPE | None = None

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Record advertisement time for presence, then let the base poll-schedule."""
        self._last_advert = dt_util.utcnow()
        # Start the self-rescheduling presence check if it isn't already running. It
        # keeps itself alive while the board advertises and stops once it goes quiet, so
        # no timer runs while the board is asleep (which is most of the time).
        if self._present_unsub is None:
            self._async_schedule_presence_check()
        super()._async_handle_bluetooth_event(service_info, change)

    @callback
    def _async_schedule_presence_check(self) -> None:
        self._present_unsub = async_call_later(
            self.hass, PRESENCE_CHECK_SECONDS, self._async_presence_check
        )

    @callback
    def _async_presence_check(self, _now: datetime) -> None:
        """Re-render entities; keep watching while present, else stop the loop."""
        self._present_unsub = None
        self.async_update_listeners()  # `present` reflects is_present
        if self.is_present:
            self._async_schedule_presence_check()

    @callback
    def async_stop_presence_tracking(self) -> None:
        """Cancel any pending presence check (called on unload)."""
        if self._present_unsub is not None:
            self._present_unsub()
            self._present_unsub = None

    @property
    def is_present(self) -> bool:
        """True if the board advertised recently (awake & in range).

        Based on the last advertisement, not HA's slow unavailable tracking, so this
        flips off ~PRESENCE_TIMEOUT_SECONDS after the board sleeps rather than minutes.
        """
        return (
            self._last_advert is not None
            and (dt_util.utcnow() - self._last_advert).total_seconds()
            < PRESENCE_TIMEOUT_SECONDS
        )

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
        # Merge into the running snapshot. The board sometimes reports only a SUBSET of
        # datapoints on a given read, so replacing wholesale would drop the unreported
        # ones and flip their entities to "unknown". Accumulate instead: a DP persists
        # once seen and is updated whenever the board re-reports it.
        merged = dict(self.data.dps) if self.data is not None else {}
        merged.update({dp.id: dp for dp in dps})
        return EboardSnapshot(dps=merged, last_seen=dt_util.utcnow())
