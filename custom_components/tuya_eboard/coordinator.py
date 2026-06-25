"""Advertisement-triggered, connect-on-demand coordinator for the e-board.

The board (an ESC) is only reachable over BLE when it's powered on and the remote is
awake - the two ends of a ride. We therefore do NOT poll in a loop: HA's passive scanner
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
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, CoreState, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_call_later
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    DP_BATTERY,
    DP_ODOMETER,
    DP_TRIP_DISTANCE,
    DP_VOLTAGE,
    EVENT_RIDE_COMPLETED,
    POLL_INTERVAL_SECONDS,
    PRESENCE_CHECK_SECONDS,
    PRESENCE_TIMEOUT_SECONDS,
    SETTLE_SECONDS,
)
from .tuya_eboard_ble._vendor.tuya_ble import TuyaBLEDeviceCredentials
from .tuya_eboard_ble._vendor.tuya_ble.exceptions import TuyaBLEError
from .tuya_eboard_ble.device import TuyaEboardDevice
from .tuya_eboard_ble.protocol import DataPoint


@dataclass
class EboardSnapshot:
    """One read of the board, kept as last-known state between polls."""

    dps: dict[int, DataPoint]
    last_seen: datetime
    # Effective last-trip distance (km x10). Normally the board's DP5, but DP5 is wiped
    # to 0 when the remote power-cycles (e.g. an off/on to sync at home), so this holds
    # a recovered value across that wipe. See _effective_trip_km10.
    trip_distance_km10: int | None = None


def _dp_int(dps: dict[int, DataPoint], dp_id: int) -> int | None:
    dp = dps.get(dp_id)
    return dp.value if dp is not None and isinstance(dp.value, int) else None


class TuyaEboardCoordinator(ActiveBluetoothDataUpdateCoordinator[EboardSnapshot]):
    """Connect-on-demand snapshot coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        entry: ConfigEntry,
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
        self._entry = entry
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
        try:
            dps = await device.read_all_dps(settle=SETTLE_SECONDS)
        except TuyaBLEError:
            # Connected but the Tuya protocol/decrypt failed -> the local_key is almost
            # certainly rotated/invalid (board re-paired); start reauth to re-pull it.
            # Transient connect/timeout errors are NOT TuyaBLEError, so they won't trip
            # this. async_start_reauth is idempotent, so repeat calls are safe.
            self._entry.async_start_reauth(self.hass)
            raise
        if not dps:
            # Empty read -> raise so the coordinator keeps the previous snapshot and
            # marks the poll unsuccessful, rather than blanking every entity.
            raise ValueError("board reported no datapoints")
        # Merge into the running snapshot. The board sometimes reports only a SUBSET of
        # datapoints on a given read, so replacing wholesale would drop the unreported
        # ones and flip their entities to "unknown". Accumulate instead: a DP persists
        # once seen and is updated whenever the board re-reports it.
        previous = self.data
        merged = dict(previous.dps) if previous is not None else {}
        merged.update({dp.id: dp for dp in dps})
        if previous is not None:
            self._async_fire_ride_event(previous.dps, merged)
        return EboardSnapshot(
            dps=merged,
            last_seen=dt_util.utcnow(),
            trip_distance_km10=self._effective_trip_km10(previous, merged),
        )

    @staticmethod
    def _effective_trip_km10(
        previous: EboardSnapshot | None, merged: dict[int, DataPoint]
    ) -> int | None:
        """Last-trip distance (km x10), recovered when the board wipes DP5.

        DP5 (mileage_once) is the board's own per-trip distance, but it resets to 0 when
        the remote is power-cycled - e.g. turning it off then back on to sync at home,
        which wipes a just-completed ride from the dashboard. When DP5 is 0 we recover:

        * if the cumulative odometer (DP12) advanced since the previous read, a ride
          happened between reads, so use that delta;
        * otherwise the odometer is flat (a reconnect/sync, no new riding) - keep the
          last known trip rather than overwriting it with 0.

        A nonzero DP5 is always trusted as-is.
        """
        raw = _dp_int(merged, DP_TRIP_DISTANCE)
        if raw:  # board reported a real per-trip distance
            return raw
        if previous is None:
            return raw  # first read: nothing to recover from (0 or None)
        odo_before = _dp_int(previous.dps, DP_ODOMETER)
        odo_after = _dp_int(merged, DP_ODOMETER)
        if odo_before is not None and odo_after is not None and odo_after > odo_before:
            return odo_after - odo_before  # ride between reads
        return previous.trip_distance_km10  # flat odometer: don't wipe the last trip

    @callback
    def _async_fire_ride_event(
        self, before: dict[int, DataPoint], after: dict[int, DataPoint]
    ) -> None:
        """Fire ``tuya_eboard_ride_completed`` if the odometer advanced.

        The board is only reachable at the ends of a ride (power-on / arrival), so an
        odometer increase between two reads *is* a completed ride. We carry the full
        delta in the event so blueprints can journal it without re-deriving anything.
        DP5/DP6 (per-trip) reset on sleep and are unreliable across power cycles, so
        distance is the cumulative-odometer delta (DP12).
        """
        odo_before = _dp_int(before, DP_ODOMETER)
        odo_after = _dp_int(after, DP_ODOMETER)
        if odo_before is None or odo_after is None or odo_after <= odo_before:
            return

        # DP12 is km x10. mi = (delta / 10) / 1.609 = delta / 16.09.
        delta = odo_after - odo_before
        soc_before = _dp_int(before, DP_BATTERY)
        soc_after = _dp_int(after, DP_BATTERY)
        v_before = _dp_int(before, DP_VOLTAGE)
        v_after = _dp_int(after, DP_VOLTAGE)

        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, self.address)})

        self.hass.bus.async_fire(
            EVENT_RIDE_COMPLETED,
            {
                "device_id": device.id if device else None,
                "name": device.name_by_user or device.name if device else None,
                "address": self.address,
                "distance_km": round(delta / 10, 2),
                "distance_mi": round(delta / 16.09, 2),
                "odometer_km": round(odo_after / 10, 2),
                "battery_used": (
                    soc_before - soc_after
                    if soc_before is not None and soc_after is not None
                    else None
                ),
                "battery_start": soc_before,
                "battery_end": soc_after,
                "voltage_start": None if v_before is None else round(v_before / 10, 1),
                "voltage_end": None if v_after is None else round(v_after / 10, 1),
            },
        )
