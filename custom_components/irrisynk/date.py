# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Date entities for IrriSynk."""

from __future__ import annotations

from datetime import date

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entities.base import IrrigationZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up date entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [IrrigationPlantingDateEntity(coordinator, zone_id) for zone_id in coordinator.zone_states]
    )


class IrrigationPlantingDateEntity(IrrigationZoneEntity, DateEntity):
    _attr_translation_key = "planting_date"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "planting_date")

    @property
    def native_value(self) -> date | None:
        return self.coordinator.zone_states[self.zone_id].planting_date

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_set_planting_date(self.zone_id, value)
