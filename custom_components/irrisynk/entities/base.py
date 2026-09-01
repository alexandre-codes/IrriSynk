# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Base entities for IrriSynk."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import IrrigationCoordinator


class IrrigationZoneEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base zone entity — one HA device per (entry, zone)."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, zone_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.zone_id = zone_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{zone_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_{zone_id}")},
            name=f"{coordinator.entry.title} – {zone_id}",
            manufacturer="IrriSynk",
        )


class IrrigationConfigEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for the Configuration device (global, non-zone settings)."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_config_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_config")},
            name="Configuration",
            manufacturer="IrriSynk",
        )


class IrrigationCropsEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for the custom Crops management device."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_crops_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_crops")},
            name="Crops" if coordinator._is_english() else "Cultures",
            manufacturer="IrriSynk",
        )


class IrrigationCultModesEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for the Cultivation Modes management device."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_cult_modes_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_cult_modes")},
            name="Cultivation Modes" if coordinator._is_english() else "Modes de culture",
            manufacturer="IrriSynk",
        )


class IrrigationCalculatorEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for the Drip Calculator device."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_calculator_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_calculator")},
            name="Calculator" if coordinator._is_english() else "Calculateur",
            manufacturer="IrriSynk",
        )


class IrrigationCascadesEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for the global Cascades management device (form + create button)."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_cascade_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_cascade_mgmt")},
            name="Cascades",
            manufacturer="IrriSynk",
        )


class IrrigationCascadeEntity(CoordinatorEntity[IrrigationCoordinator]):
    """Base entity for a single cascade group device."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: IrrigationCoordinator, cascade_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.cascade_id = cascade_id
        self._attr_unique_id = f"{coordinator.entry.entry_id}_cascade_{cascade_id}_{key}"
        cascade = next((c for c in coordinator.cascades if c.cascade_id == cascade_id), None)
        device_name = cascade.name if cascade else cascade_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_cascade_{cascade_id}")},
            name=device_name,
            manufacturer="IrriSynk",
        )
