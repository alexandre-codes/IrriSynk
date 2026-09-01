# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Sensor entities for IrriSynk."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import IrrigationCoordinator
from .entities.base import IrrigationCalculatorEntity, IrrigationZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [Et0Sensor(coordinator), CalcResultSensor(coordinator)]
    for zone_id in coordinator.zone_states:
        entities.extend(
            [
                WaterNeedSensor(coordinator, zone_id),
                EffectiveRainSensor(coordinator, zone_id),
                IrrigationTodaySensor(coordinator, zone_id),
                DurationSensor(coordinator, zone_id),
                EffectiveDurationSensor(coordinator, zone_id),
                SoilWaterBalanceSensor(coordinator, zone_id),
                SoilCapacitySensor(coordinator, zone_id),
                ConfidenceSensor(coordinator, zone_id),
                StageCurrentSensor(coordinator, zone_id),
                KcCurrentSensor(coordinator, zone_id),
            ]
        )
    async_add_entities(entities)


class Et0Sensor(CoordinatorEntity[IrrigationCoordinator], SensorEntity):
    """Daily ET0 (FAO-56) sensor — integration-level device."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm"
    _attr_translation_key = "et0_daily"
    _attr_icon = "mdi:sun-thermometer-outline"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_et0_daily"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name="ET0" if coordinator._is_english() else "ETP",
            manufacturer="IrriSynk",
        )

    @property
    def native_value(self) -> float:
        return self.coordinator.et0_mm


class KcCurrentSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "kc_current"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "kc_current")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].kc_current


class StageCurrentSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "current_stage"
    _attr_icon = "mdi:compost"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "current_stage")

    @property
    def native_value(self) -> str:
        return self.coordinator.data[self.zone_id].current_stage_label

    @property
    def extra_state_attributes(self):
        return {"stage_id": self.coordinator.data[self.zone_id].current_stage_id}


class WaterNeedSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "water_need_mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm"
    _attr_icon = "mdi:water-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "water_need_mm")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].water_need_mm


class DurationSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "recommended_duration_min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "recommended_duration_min")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].recommended_duration_min


class EffectiveDurationSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "effective_duration_min"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-play-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "effective_duration_min")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].effective_duration_min


class EffectiveRainSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "effective_rain_mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm"
    _attr_icon = "mdi:weather-rainy"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "effective_rain_mm")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].effective_rain_mm


class IrrigationTodaySensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "irrigation_today_mm"
    _attr_state_class = SensorStateClass.TOTAL
    _attr_native_unit_of_measurement = "mm"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:watering-can-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "irrigation_today_mm")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].irrigation_today_mm

    @property
    def last_reset(self):
        return dt_util.start_of_local_day(dt_util.now())


class ConfidenceSensor(IrrigationZoneEntity, SensorEntity):
    _attr_translation_key = "confidence"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "confidence")

    @property
    def native_value(self):
        return self.coordinator.data[self.zone_id].confidence

    @property
    def extra_state_attributes(self):
        return {"notes": self.coordinator.data[self.zone_id].notes}


class SoilWaterBalanceSensor(IrrigationZoneEntity, SensorEntity):
    """J-1 water balance: positive = surplus, negative = deficit."""

    _attr_translation_key = "soil_water_balance_mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "soil_water_balance_mm")

    @property
    def native_value(self) -> float:
        return self.coordinator.data[self.zone_id].soil_water_balance_mm


class SoilCapacitySensor(IrrigationZoneEntity, SensorEntity):
    """RAW = 0.4 × TAW: readily available water for current soil type and root depth."""

    _attr_translation_key = "soil_capacity_mm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm"
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:cup-water"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "soil_capacity_mm")

    @property
    def native_value(self) -> float:
        return self.coordinator.data[self.zone_id].soil_capacity_mm


class CalcResultSensor(IrrigationCalculatorEntity, SensorEntity):
    """Drip calculator result: mm/m²/h."""

    _attr_translation_key = "calc_result_mm_h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm/h"
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:water-percent"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "result_mm_h")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.forms.calc_result_mm_h
