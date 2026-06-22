"""Base entity for Tuya E-Board (BLE)."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
)
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import DOMAIN
from .coordinator import TuyaEboardCoordinator


class TuyaEboardEntity(PassiveBluetoothCoordinatorEntity[TuyaEboardCoordinator]):
    """Common device wiring + last-known availability semantics."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TuyaEboardCoordinator,
        address: str,
        model: str | None,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._address = address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            connections={(CONNECTION_BLUETOOTH, address)},
            identifiers={(DOMAIN, address)},
            name=model or "Tuya E-Board",
            manufacturer="Tuya / Hobbywing",
            model=model,
        )

    @property
    def available(self) -> bool:
        """Stay available on the last-known snapshot.

        The board sleeps when idle, so advertisement presence (coordinator.available)
        is intermittent by design. We keep showing the last reading and surface
        freshness via the ``last_seen`` sensor and the ``present`` binary sensor,
        rather than blanking every entity the moment the board sleeps.
        """
        return self.coordinator.data is not None
