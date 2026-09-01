# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Button entities for IrriSynk."""

from __future__ import annotations

import logging
import re

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IrrigationCoordinator
from .entities.base import IrrigationCalculatorEntity, IrrigationCascadeEntity, IrrigationCascadesEntity, IrrigationConfigEntity, IrrigationCropsEntity, IrrigationCultModesEntity, IrrigationZoneEntity

_LOGGER = logging.getLogger(__name__)

_ZONE_STAT_SENSOR_KEYS = [
    "water_need_mm",
    "irrigation_today_mm",
    "recommended_duration_min",
    "current_stage",
    "kc_current",
    "soil_water_balance_mm",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: IrrigationCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        AddZoneButton(coordinator),
        AllZonesRecalculateButton(coordinator),
        AllZonesResetButton(coordinator),
        CalculatorButton(coordinator),
        AddCultModeButton(coordinator),
        CreateCropButton(coordinator),
        AddStageButton(coordinator),
        CreateCascadeButton(coordinator),
    ]
    for mode in coordinator.custom_cultivation_modes:
        entities.append(DeleteCultModeButton(coordinator, mode.name))
    coordinator._cult_modes_add_button_entities = async_add_entities
    for crop in coordinator.custom_crops:
        entities.append(DeleteCropButton(coordinator, crop.crop_id))
        for stage in crop.stages:
            entities.append(DeleteStageButton(coordinator, crop.crop_id, stage.stage_id))
    entities.append(SaveStageButton(coordinator))
    coordinator._crops_add_button_entities = async_add_entities
    for cascade in coordinator.cascades:
        entities.append(DeleteCascadeButton(coordinator, cascade.cascade_id))
        entities.append(AddZoneToCascadeButton(coordinator, cascade.cascade_id))
    coordinator._cascades_add_button_entities = async_add_entities
    for zone_id in coordinator.zone_states:
        entities.append(DeleteZoneButton(coordinator, zone_id))
        entities.append(ResetStatsButton(coordinator, zone_id))
        entities.append(RecalculateButton(coordinator, zone_id))
    async_add_entities(entities)


class AddZoneButton(CoordinatorEntity[IrrigationCoordinator], ButtonEntity):
    """Adds one zone (zone_N+1) and reloads the integration."""

    _attr_has_entity_name = True
    _attr_entity_registry_visible_default = False
    _attr_translation_key = "add_zone"
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_config_add_zone"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_config")},
            name="Configuration",
            manufacturer="IrriSynk",
        )

    async def async_press(self) -> None:
        entry = self.coordinator.entry
        current_zones: list[str] = list(
            entry.options.get("zones", entry.data.get("zones", []))
        )
        highest = 0
        for z in current_zones:
            m = re.match(r"^zone_(\d+)$", z)
            if m:
                highest = max(highest, int(m.group(1)))
        new_zone = f"zone_{highest + 1}"
        updated_options = {**entry.options, "zones": current_zones + [new_zone]}
        self.hass.config_entries.async_update_entry(entry, options=updated_options)
        await self.hass.config_entries.async_reload(entry.entry_id)


class DeleteZoneButton(IrrigationZoneEntity, ButtonEntity):
    """Removes this zone from the config and reloads the integration."""

    _attr_translation_key = "delete_zone"
    _attr_icon = "mdi:delete"

    def __init__(self, coordinator: IrrigationCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "delete_zone")

    async def async_press(self) -> None:
        entry = self.coordinator.entry
        current_zones: list[str] = list(
            entry.options.get("zones", entry.data.get("zones", []))
        )
        updated_zones = [z for z in current_zones if z != self.zone_id]
        updated_options = {**entry.options, "zones": updated_zones}
        self.hass.config_entries.async_update_entry(entry, options=updated_options)
        await self.hass.config_entries.async_reload(entry.entry_id)


class ResetStatsButton(IrrigationZoneEntity, ButtonEntity):
    """Clears recorder statistics for the zone sensors and its switch, then recalculates."""

    _attr_translation_key = "reset_stats"
    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: IrrigationCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "reset_stats")

    async def async_press(self) -> None:
        from homeassistant.components.recorder import get_instance

        ent_reg = er.async_get(self.hass)
        entry_id = self.coordinator.entry.entry_id

        statistic_ids: list[str] = []
        for key in _ZONE_STAT_SENSOR_KEYS:
            entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_{self.zone_id}_{key}")
            if entity_id:
                statistic_ids.append(entity_id)

        if statistic_ids:
            get_instance(self.hass).async_clear_statistics(statistic_ids)

        switch_entity_id = self.coordinator.zone_states[self.zone_id].switch_entity_id
        if switch_entity_id:
            await self.hass.services.async_call(
                "recorder",
                "purge_entities",
                {"entity_id": [switch_entity_id], "keep_days": 0},
                blocking=True,
            )

        # Reset J-1 balance and force irrigation_today_mm=0 for next cycle
        await self.coordinator.async_reset_soil_balance(self.zone_id)
        self.coordinator._zones_irrigation_reset.add(self.zone_id)
        await self.coordinator.async_refresh()


class RecalculateButton(IrrigationZoneEntity, ButtonEntity):
    """Forces an immediate recalculation of all zone sensors."""

    _attr_translation_key = "recalculate"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: IrrigationCoordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "recalculate")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class AllZonesRecalculateButton(IrrigationConfigEntity, ButtonEntity):
    """Forces an immediate recalculation for every zone at once."""

    _attr_translation_key = "all_recalculate"
    _attr_icon = "mdi:refresh-circle"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "all_recalculate")

    async def async_press(self) -> None:
        await self.coordinator.async_refresh()


class AllZonesResetButton(IrrigationConfigEntity, ButtonEntity):
    """Clears statistics and resets soil balance for every zone at once."""

    _attr_translation_key = "all_reset_stats"
    _attr_icon = "mdi:restore-alert"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "all_reset")

    async def async_press(self) -> None:
        from homeassistant.components.recorder import get_instance

        ent_reg = er.async_get(self.hass)
        entry_id = self.coordinator.entry.entry_id

        for zone_id in self.coordinator.zone_states:
            statistic_ids: list[str] = []
            for key in _ZONE_STAT_SENSOR_KEYS:
                entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, f"{entry_id}_{zone_id}_{key}")
                if entity_id:
                    statistic_ids.append(entity_id)
            if statistic_ids:
                get_instance(self.hass).async_clear_statistics(statistic_ids)

            switch_entity_id = self.coordinator.zone_states[zone_id].switch_entity_id
            if switch_entity_id:
                await self.hass.services.async_call(
                    "recorder",
                    "purge_entities",
                    {"entity_id": [switch_entity_id], "keep_days": 0},
                    blocking=True,
                )

            await self.coordinator.async_reset_soil_balance(zone_id)
            self.coordinator._zones_irrigation_reset.add(zone_id)

        await self.coordinator.async_refresh()


class CalculatorButton(IrrigationCalculatorEntity, ButtonEntity):
    """Triggers drip flow rate calculation."""

    _attr_translation_key = "calc_run"
    _attr_icon = "mdi:calculator"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "run")

    async def async_press(self) -> None:
        await self.coordinator.async_run_calculator()


class AddCultModeButton(IrrigationCultModesEntity, ButtonEntity):
    """Adds the new custom cultivation mode from the form inputs."""

    _attr_translation_key = "add_cult_mode"
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "add")

    async def async_press(self) -> None:
        await self.coordinator.async_add_cultivation_mode()


class DeleteCultModeButton(IrrigationCultModesEntity, ButtonEntity):
    """Removes a specific custom cultivation mode."""

    _attr_icon = "mdi:delete"
    _attr_translation_key = "delete_cult_mode"

    def __init__(self, coordinator: IrrigationCoordinator, mode_name: str) -> None:
        super().__init__(coordinator, f"delete_{mode_name}")
        self._mode_name = mode_name

    async def async_press(self) -> None:
        await self.coordinator.async_delete_cultivation_mode(self._mode_name)


class CreateCropButton(IrrigationCropsEntity, ButtonEntity):
    """Creates a new empty custom crop from the name form input."""

    _attr_translation_key = "create_crop"
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "create_crop")

    async def async_press(self) -> None:
        await self.coordinator.async_create_crop()


class AddStageButton(IrrigationCropsEntity, ButtonEntity):
    """Adds a stage to the selected custom crop."""

    _attr_translation_key = "add_stage"
    _attr_icon = "mdi:numeric-positive-1"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "add_stage")

    async def async_press(self) -> None:
        await self.coordinator.async_add_stage_to_crop()


class DeleteCropButton(IrrigationCropsEntity, ButtonEntity):
    """Deletes a specific custom crop."""

    _attr_translation_key = "delete_crop"
    _attr_icon = "mdi:delete"

    def __init__(self, coordinator: IrrigationCoordinator, crop_id: str) -> None:
        super().__init__(coordinator, f"delete_{crop_id}")
        self._crop_id = crop_id

    async def async_press(self) -> None:
        await self.coordinator.async_delete_custom_crop(self._crop_id)


class DeleteStageButton(IrrigationCropsEntity, ButtonEntity):
    """Deletes a specific stage from a custom crop."""

    _attr_translation_key = "delete_stage"
    _attr_icon = "mdi:delete-outline"

    def __init__(self, coordinator: IrrigationCoordinator, crop_id: str, stage_id: str) -> None:
        super().__init__(coordinator, f"delete_stage_{crop_id}_{stage_id}")
        self._crop_id = crop_id
        self._stage_id = stage_id

    async def async_press(self) -> None:
        await self.coordinator.async_delete_stage(self._crop_id, self._stage_id)


class SaveStageButton(IrrigationCropsEntity, ButtonEntity):
    """Saves edits to the currently selected stage."""

    _attr_translation_key = "save_stage"
    _attr_icon = "mdi:content-save-outline"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "save_stage")

    async def async_press(self) -> None:
        await self.coordinator.async_submit_stage_form()


class CreateCascadeButton(IrrigationCascadesEntity, ButtonEntity):
    """Creates a new cascade group from the form fields."""

    _attr_translation_key = "cascade_create"
    _attr_icon = "mdi:plus-circle"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "create")

    async def async_press(self) -> None:
        await self.coordinator.async_add_cascade()


class DeleteCascadeButton(IrrigationCascadeEntity, ButtonEntity):
    """Deletes a cascade group and removes all its entities."""

    _attr_translation_key = "cascade_delete"
    _attr_icon = "mdi:delete-outline"

    def __init__(self, coordinator: IrrigationCoordinator, cascade_id: str) -> None:
        super().__init__(coordinator, cascade_id, "delete")

    async def async_press(self) -> None:
        await self.coordinator.async_remove_cascade(self.cascade_id)


class AddZoneToCascadeButton(IrrigationCascadeEntity, ButtonEntity):
    """Adds the selected zone to this cascade group."""

    _attr_translation_key = "cascade_add_zone"
    _attr_icon = "mdi:plus"

    def __init__(self, coordinator: IrrigationCoordinator, cascade_id: str) -> None:
        super().__init__(coordinator, cascade_id, "add_zone")

    async def async_press(self) -> None:
        zone_id = self.coordinator._cascade_selector_state.get(self.cascade_id)
        if zone_id:
            await self.coordinator.async_add_zone_to_cascade(self.cascade_id, zone_id)
