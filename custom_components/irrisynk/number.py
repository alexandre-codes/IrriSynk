# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Number entities for IrriSynk."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.base import IrrigationCalculatorEntity, IrrigationConfigEntity, IrrigationCropsEntity, IrrigationCultModesEntity, IrrigationZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up number entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[NumberEntity] = [
        AllZonesMaxDurationNumber(coordinator),
        AllZonesRainEffectivenessNumber(coordinator),
        AllZonesSoilBufferNumber(coordinator),
        CultModeEt0Number(coordinator),
        CropFormRootDepthNumber(coordinator),
        StageFormKcNumber(coordinator),
        StageFormDurationOpenNumber(coordinator),
        StageFormDurationGhNumber(coordinator),
        EditStageKcNumber(coordinator),
        EditStageDurationOpenNumber(coordinator),
        EditStageDurationGhNumber(coordinator),
        CalcFlowLhNumber(coordinator),
        CalcDripperSpacingNumber(coordinator),
        CalcLineCountNumber(coordinator),
        CalcLineSpacingNumber(coordinator),
        CalcLineLengthNumber(coordinator),
        CalcZoneWidthNumber(coordinator),
    ]
    for zone_id in coordinator.zone_states:
        entities.extend(
            [
                ZoneScheduledDurationNumber(coordinator, zone_id),
                ZoneFlowMmhNumber(coordinator, zone_id),
                ZoneMaxDurationNumber(coordinator, zone_id),
                ZoneRainEffectivenessNumber(coordinator, zone_id),
                ZoneSoilBufferNumber(coordinator, zone_id),
                ZoneEt0CorrectionFactorNumber(coordinator, zone_id),
            ]
        )
    async_add_entities(entities)


class ZoneMaxDurationNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "max_duration_min"
    _attr_icon = "mdi:timer-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "max_duration_min")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].max_duration_min

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number(self.zone_id, "max_duration_min", value)


class ZoneRainEffectivenessNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "rain_effectiveness_pct"
    _attr_icon = "mdi:weather-rainy"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "rain_effectiveness_pct")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].rain_effectiveness_pct

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number(self.zone_id, "rain_effectiveness_pct", value)


class ZoneEt0CorrectionFactorNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "et0_correction_factor"
    _attr_icon = "mdi:sun-thermometer-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.1
    _attr_native_max_value = 2.0
    _attr_native_step = 0.05

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "et0_correction_factor")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].et0_correction_factor

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number(self.zone_id, "et0_correction_factor", value)


class ZoneSoilBufferNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "soil_buffer_mm"
    _attr_icon = "mdi:water-check"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 20
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "mm"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "soil_buffer_mm")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].soil_buffer_mm

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number(self.zone_id, "soil_buffer_mm", value)


# ---------------------------------------------------------------------------
# Global "all zones" number setters
# ---------------------------------------------------------------------------

class AllZonesMaxDurationNumber(IrrigationConfigEntity, NumberEntity):
    _attr_translation_key = "all_max_duration_min"
    _attr_icon = "mdi:timer-outline"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "all_max_duration_min")

    @property
    def native_value(self) -> float:
        if not self.coordinator.zone_states:
            return 60.0
        return next(iter(self.coordinator.zone_states.values())).max_duration_min

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_all_zones_number("max_duration_min", value)


class AllZonesRainEffectivenessNumber(IrrigationConfigEntity, NumberEntity):
    _attr_translation_key = "all_rain_effectiveness_pct"
    _attr_icon = "mdi:weather-rainy"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "all_rain_effectiveness_pct")

    @property
    def native_value(self) -> float:
        if not self.coordinator.zone_states:
            return 80.0
        return next(iter(self.coordinator.zone_states.values())).rain_effectiveness_pct

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_all_zones_number("rain_effectiveness_pct", value)


class AllZonesSoilBufferNumber(IrrigationConfigEntity, NumberEntity):
    _attr_translation_key = "all_soil_buffer_mm"
    _attr_icon = "mdi:water-check"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 20
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "mm"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "all_soil_buffer_mm")

    @property
    def native_value(self) -> float:
        if not self.coordinator.zone_states:
            return 0.0
        return next(iter(self.coordinator.zone_states.values())).soil_buffer_mm

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_all_zones_number("soil_buffer_mm", value)


class ZoneScheduledDurationNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "scheduled_duration_min"
    _attr_icon = "mdi:timer-edit-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1
    _attr_native_unit_of_measurement = "min"
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "scheduled_duration_min")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].scheduled_duration_min

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_scheduled_duration(self.zone_id, value)


class ZoneFlowMmhNumber(IrrigationZoneEntity, NumberEntity):
    _attr_translation_key = "flow_mm_h"
    _attr_icon = "mdi:pipe"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.1
    _attr_native_max_value = 50.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "mm/h"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "flow_mm_h")

    @property
    def native_value(self) -> float:
        return self.coordinator.zone_states[self.zone_id].flow_mm_h

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_number(self.zone_id, "flow_mm_h", value)


# ---------------------------------------------------------------------------
# Drip calculator input entities
# ---------------------------------------------------------------------------

class CalcFlowLhNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_flow_lh"
    _attr_icon = "mdi:water-pump"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.1
    _attr_native_max_value = 20.0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = "L/h"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "flow_lh")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_flow_lh

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_flow_lh = value
        self.async_write_ha_state()


class CalcDripperSpacingNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_dripper_spacing_cm"
    _attr_icon = "mdi:ruler"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 5.0
    _attr_native_max_value = 200.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "cm"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "dripper_spacing_cm")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_dripper_spacing_cm

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_dripper_spacing_cm = value
        self.async_write_ha_state()


class CalcLineCountNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_line_count"
    _attr_icon = "mdi:numeric"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "line_count")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_line_count

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_line_count = value
        self.async_write_ha_state()


class CalcLineSpacingNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_line_spacing_cm"
    _attr_icon = "mdi:ruler"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 5.0
    _attr_native_max_value = 300.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = "cm"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "line_spacing_cm")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_line_spacing_cm

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_line_spacing_cm = value
        self.async_write_ha_state()


class CalcLineLengthNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_line_length_m"
    _attr_icon = "mdi:arrow-expand-horizontal"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.5
    _attr_native_max_value = 500.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "m"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "line_length_m")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_line_length_m

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_line_length_m = value
        self.async_write_ha_state()


class CalcZoneWidthNumber(IrrigationCalculatorEntity, NumberEntity):
    _attr_translation_key = "calc_zone_width_m"
    _attr_icon = "mdi:arrow-expand-horizontal"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.5
    _attr_native_max_value = 500.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = "m"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "zone_width_m")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.calc_zone_width_m

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.calc_zone_width_m = value
        self.async_write_ha_state()


class CultModeEt0Number(IrrigationCultModesEntity, NumberEntity):
    _attr_translation_key = "cult_mode_et0"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.1
    _attr_native_max_value = 2.0
    _attr_native_step = 0.05
    _attr_icon = "mdi:sun-thermometer-outline"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_et0")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.cult_mode_form_et0

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.cult_mode_form_et0 = value
        self.async_write_ha_state()


class CropFormRootDepthNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "crop_form_root_depth"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 10
    _attr_native_max_value = 300
    _attr_native_step = 5
    _attr_native_unit_of_measurement = "cm"
    _attr_icon = "mdi:arrow-expand-down"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_crop_root_depth")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.forms.crop_form_root_depth)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.crop_form_root_depth = int(value)
        self.async_write_ha_state()


class StageFormKcNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "stage_form_kc"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.1
    _attr_native_max_value = 2.0
    _attr_native_step = 0.05
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_stage_kc")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.stage_form_kc

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_form_kc = value
        self.async_write_ha_state()


class StageFormDurationOpenNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "stage_form_duration_open"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_stage_dur_open")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.forms.stage_form_duration_open)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_form_duration_open = int(value)
        self.async_write_ha_state()


class StageFormDurationGhNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "stage_form_duration_gh"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:greenhouse"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_stage_dur_gh")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.forms.stage_form_duration_gh)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_form_duration_gh = int(value)
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Stage edit form entities
# ---------------------------------------------------------------------------

class EditStageKcNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "edit_stage_kc"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.05
    _attr_native_max_value = 2.0
    _attr_native_step = 0.05
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_kc")

    @property
    def native_value(self) -> float:
        return self.coordinator.forms.stage_edit_kc

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_edit_kc = value
        self.async_write_ha_state()


class EditStageDurationOpenNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "edit_stage_duration_open"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:weather-sunny"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_dur_open")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.forms.stage_edit_duration_open)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_edit_duration_open = int(value)
        self.async_write_ha_state()


class EditStageDurationGhNumber(IrrigationCropsEntity, NumberEntity):
    _attr_translation_key = "edit_stage_duration_gh"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 365
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_icon = "mdi:greenhouse"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_dur_gh")

    @property
    def native_value(self) -> float:
        return float(self.coordinator.forms.stage_edit_duration_gh)

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.forms.stage_edit_duration_gh = int(value)
        self.async_write_ha_state()
