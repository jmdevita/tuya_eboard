"""Binary sensor platform for Tuya E-Board (BLE)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_ADDRESS, CONF_PRODUCT_ID
from .coordinator import TuyaEboardCoordinator
from .data import TuyaEboardConfigEntry
from .dpmap import device_meta
from .entity import TuyaEboardEntity

# Read-only, all state served from one shared coordinator snapshot — no per-entity I/O.
PARALLEL_UPDATES = 0


def _dp_bool(coordinator: TuyaEboardCoordinator, dp_id: int) -> bool | None:
    if (snapshot := coordinator.data) is None:
        return None
    dp = snapshot.dps.get(dp_id)
    return bool(dp.value) if dp is not None else None


@dataclass(frozen=True, kw_only=True)
class EboardBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor over the snapshot (dp-based) or live presence."""

    is_on_fn: Callable[[TuyaEboardCoordinator], bool | None]
    # `present` must stay available to report on/off even while the board is asleep.
    live_presence: bool = False


BINARY_SENSORS: tuple[EboardBinarySensorDescription, ...] = (
    EboardBinarySensorDescription(
        key="cruise",
        translation_key="cruise",
        is_on_fn=lambda c: _dp_bool(c, 13),  # DP13 cruise_switch
    ),
    EboardBinarySensorDescription(
        key="ble_lock",
        translation_key="ble_lock",
        is_on_fn=lambda c: _dp_bool(c, 1),  # DP1 blelock_switch (on = locked)
    ),
    EboardBinarySensorDescription(
        key="present",
        translation_key="present",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        is_on_fn=lambda c: c.available,  # advertising now (awake & in range)
        live_presence=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaEboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the e-board binary sensors."""
    coordinator = entry.runtime_data
    address = entry.data[CONF_ADDRESS]
    model = device_meta(entry.data.get(CONF_PRODUCT_ID)).get("board") or entry.title
    async_add_entities(
        TuyaEboardBinarySensor(coordinator, address, model, description)
        for description in BINARY_SENSORS
    )


class TuyaEboardBinarySensor(TuyaEboardEntity, BinarySensorEntity):
    """A read-only e-board binary sensor."""

    entity_description: EboardBinarySensorDescription

    def __init__(
        self,
        coordinator,
        address: str,
        model: str | None,
        description: EboardBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, address, model, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        # The presence sensor itself stays available (it reports on/off); others
        # follow the base last-known rule.
        if self.entity_description.live_presence:
            return self.coordinator.data is not None or self.coordinator.available
        return super().available

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.is_on_fn(self.coordinator)
