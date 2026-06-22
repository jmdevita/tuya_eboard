"""Sensor platform for Tuya E-Board (BLE) — read-only, last-known."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CONF_ADDRESS, CONF_PRODUCT_ID
from .coordinator import EboardSnapshot
from .data import TuyaEboardConfigEntry
from .dpmap import device_meta
from .entity import TuyaEboardEntity

# Read-only, all state served from one shared coordinator snapshot — no per-entity I/O.
PARALLEL_UPDATES = 0


def _dp_int(snapshot: EboardSnapshot, dp_id: int) -> int | None:
    dp = snapshot.dps.get(dp_id)
    return dp.value if dp is not None and isinstance(dp.value, int) else None


def _scaled(dp_id: int, factor: float) -> Callable[[EboardSnapshot], StateType]:
    def _fn(snapshot: EboardSnapshot) -> StateType:
        raw = _dp_int(snapshot, dp_id)
        return None if raw is None else round(raw * factor, 2)

    return _fn


@dataclass(frozen=True, kw_only=True)
class EboardSensorDescription(SensorEntityDescription):
    """A sensor backed by a transform over the DP snapshot."""

    value_fn: Callable[[EboardSnapshot], StateType | datetime]


SENSORS: tuple[EboardSensorDescription, ...] = (
    EboardSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: _dp_int(s, 3),  # DP3 battery_percentage
    ),
    EboardSensorDescription(
        key="voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_scaled(20, 0.1),  # DP20 voltage_current ÷10 (12S, full ≈ 50.2 V)
    ),
    EboardSensorDescription(
        key="odometer",
        translation_key="odometer",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=_scaled(12, 0.1),  # DP12 mileage_total ÷10 (km; HA converts to mi)
    ),
    EboardSensorDescription(
        key="trip_distance",
        translation_key="trip_distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_scaled(5, 0.1),  # DP5 mileage_once ÷10 (resets when board sleeps)
    ),
    EboardSensorDescription(
        key="trip_time",
        translation_key="trip_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda s: _dp_int(s, 6),  # DP6 ridetime_once
    ),
    EboardSensorDescription(
        key="speed_mode",
        translation_key="speed_mode",
        # No state_class: mode is an ordinal (1–4), not a measurement to average.
        value_fn=lambda s: (
            None if (v := _dp_int(s, 14)) is None else v + 1  # DP14 level (0-indexed)
        ),
    ),
    EboardSensorDescription(
        key="last_seen",
        translation_key="last_seen",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda s: s.last_seen,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TuyaEboardConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the e-board sensors."""
    coordinator = entry.runtime_data
    address = entry.data[CONF_ADDRESS]
    model = device_meta(entry.data.get(CONF_PRODUCT_ID)).get("board") or entry.title
    async_add_entities(
        TuyaEboardSensor(coordinator, address, model, description)
        for description in SENSORS
    )


class TuyaEboardSensor(TuyaEboardEntity, SensorEntity):
    """A read-only e-board sensor over the DP snapshot."""

    entity_description: EboardSensorDescription

    def __init__(
        self,
        coordinator,
        address: str,
        model: str | None,
        description: EboardSensorDescription,
    ) -> None:
        super().__init__(coordinator, address, model, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | datetime:
        if (snapshot := self.coordinator.data) is None:
            return None
        return self.entity_description.value_fn(snapshot)
