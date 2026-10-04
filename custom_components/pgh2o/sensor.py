"""Sensors that show how recent the PGH2O data is."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import PGH2OConfigEntry
from .api import hourly_points
from .const import DOMAIN
from .coordinator import PGH2OCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PGH2OConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([DataThroughSensor(coordinator), LastDaySensor(coordinator)])


class _Base(CoordinatorEntity[PGH2OCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: PGH2OCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        account = coordinator.data.account
        self._attr_unique_id = f"{account}_{key}"
        self._attr_name = name
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, account)},
            name=f"PGH2O {account}",
            manufacturer="Pittsburgh Water",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def _points(self):
        return hourly_points(self.coordinator.data)


class DataThroughSensor(_Base):
    """End of the last hour with final data."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PGH2OCoordinator) -> None:
        super().__init__(coordinator, "data_through", "Data through")

    @property
    def native_value(self) -> datetime | None:
        pts = self._points
        return pts[-1][0] + timedelta(hours=1) if pts else None


class LastDaySensor(_Base):
    """Gallons in the last 24 hours of final data (not a rolling total of today)."""

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS

    def __init__(self, coordinator: PGH2OCoordinator) -> None:
        super().__init__(coordinator, "last_24h", "Usage in last 24 h of data")

    @property
    def native_value(self) -> float | None:
        pts = self._points
        return sum(g for _, g in pts[-24:]) if pts else None
