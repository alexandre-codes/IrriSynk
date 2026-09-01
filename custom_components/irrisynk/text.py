# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Text entities for IrriSynk (switch entity assignment per zone)."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .dashboard import async_update_dashboard
from .entities.base import IrrigationCascadesEntity, IrrigationCropsEntity, IrrigationCultModesEntity, IrrigationZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up text entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[TextEntity] = [
        ZoneDeviceNameText(coordinator, zone_id) for zone_id in coordinator.zone_states
    ]
    entities.append(CultModeNameText(coordinator))
    entities.append(CropFormNameText(coordinator))
    entities.append(StageFormNameText(coordinator))
    entities.append(EditStageNameText(coordinator))
    entities.append(CascadeFormNameText(coordinator))
    async_add_entities(entities)


class ZoneDeviceNameText(IrrigationZoneEntity, TextEntity):
    """Editable display name for the zone device."""

    _attr_translation_key = "zone_name"
    _attr_icon = "mdi:rename"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "zone_name")

    @property
    def native_value(self) -> str:
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{self.coordinator.entry.entry_id}_{self.zone_id}")}
        )
        if device:
            return device.name_by_user or device.name or self.zone_id
        return self.zone_id

    async def async_set_value(self, value: str) -> None:
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{self.coordinator.entry.entry_id}_{self.zone_id}")}
        )
        if device:
            dev_reg.async_update_device(device.id, name_by_user=value.strip() or None)
        self.async_write_ha_state()
        self.hass.async_create_task(async_update_dashboard(self.hass))


class CultModeNameText(IrrigationCultModesEntity, TextEntity):
    """Name field for the new cultivation mode form."""

    _attr_translation_key = "cult_mode_name"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None
    _attr_icon = "mdi:tag-text"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.forms.cult_mode_form_name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.forms.cult_mode_form_name = value
        self.async_write_ha_state()


class CropFormNameText(IrrigationCropsEntity, TextEntity):
    """Name field for the new crop form."""

    _attr_translation_key = "crop_form_name"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_crop_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.forms.crop_form_name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.forms.crop_form_name = value
        self.async_write_ha_state()


class StageFormNameText(IrrigationCropsEntity, TextEntity):
    """Name field for the new stage form."""

    _attr_translation_key = "stage_form_name"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None
    _attr_icon = "mdi:tag-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_stage_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.forms.stage_form_name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.forms.stage_form_name = value
        self.async_write_ha_state()


class EditStageNameText(IrrigationCropsEntity, TextEntity):
    """Name field for the stage edit form."""

    _attr_translation_key = "edit_stage_name"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None
    _attr_icon = "mdi:pencil-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.forms.stage_edit_name

    async def async_set_value(self, value: str) -> None:
        self.coordinator.forms.stage_edit_name = value
        self.async_write_ha_state()


class CascadeFormNameText(IrrigationCascadesEntity, TextEntity):
    """Name field for the new cascade creation form."""

    _attr_translation_key = "cascade_form_name"
    _attr_native_min = 0
    _attr_native_max = 64
    _attr_pattern = None
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_name")

    @property
    def native_value(self) -> str:
        return self.coordinator.forms.cascade_form_name

    async def async_set_value(self, value: str) -> None:
        await self.coordinator.async_set_cascade_form_name(value)
        self.async_write_ha_state()

