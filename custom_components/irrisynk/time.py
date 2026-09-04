# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Time entities for IrriSynk."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IrrigationCoordinator
from .entities.base import IrrigationCascadeEntity, IrrigationCascadesEntity, IrrigationZoneEntity

try:
    from homeassistant.helpers import entity_registry as er
except ImportError:
    er = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up time entities."""
    coordinator: IrrigationCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Remove legacy global cascade time entity (migration from single-cascade design)
    if er:
        ent_reg = er.async_get(hass)
        old_uid = f"{entry.entry_id}_config_cascade_time"
        old_eid = ent_reg.async_get_entity_id("time", DOMAIN, old_uid)
        if old_eid:
            ent_reg.async_remove(old_eid)
    entities: list[TimeEntity] = [CascadeFormTimeEntity(coordinator)]
    for cascade in coordinator.cascades:
        entities.append(CascadeGroupTimeEntity(coordinator, cascade.cascade_id))
    entities += [
        ZoneStartTimeEntity(coordinator, zone_id)
        for zone_id in coordinator.zone_states
    ]
    coordinator._cascades_add_time_entities = async_add_entities
    async_add_entities(entities)


class CascadeGroupTimeEntity(IrrigationCascadeEntity, TimeEntity):
    """Start time for one cascade group."""

    _attr_translation_key = "cascade_time"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: IrrigationCoordinator, cascade_id: str) -> None:
        super().__init__(coordinator, cascade_id, "time")

    @property
    def native_value(self) -> time | None:
        cascade = next((c for c in self.coordinator.cascades if c.cascade_id == self.cascade_id), None)
        val = cascade.start_time if cascade else None
        if not val:
            return None
        try:
            h, m = val.split(":")
            return time(int(h), int(m))
        except (ValueError, AttributeError):
            return None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_cascade_time(
            self.cascade_id, f"{value.hour:02d}:{value.minute:02d}"
        )


class CascadeFormTimeEntity(IrrigationCascadesEntity, TimeEntity):
    """Start time field in the new-cascade creation form."""

    _attr_translation_key = "cascade_time"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "form_time")

    @property
    def native_value(self) -> time | None:
        val = self.coordinator.forms.cascade_form_time
        if not val:
            return None
        try:
            h, m = val.split(":")
            return time(int(h), int(m))
        except (ValueError, AttributeError):
            return None

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_set_cascade_form_time(
            f"{value.hour:02d}:{value.minute:02d}"
        )


class ZoneStartTimeEntity(IrrigationZoneEntity, TimeEntity):
    """Start time for automatic irrigation of a zone."""

    _attr_translation_key = "start_time"
    _attr_icon = "mdi:clock-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "start_time")

    @property
    def native_value(self) -> time | None:
        val = self.coordinator.zone_states[self.zone_id].start_time_str
        if not val:
            return None
        try:
            h, m = val.split(":")
            return time(int(h), int(m))
        except (ValueError, AttributeError):
            return None

    async def async_set_value(self, value: time) -> None:
        time_str = f"{value.hour:02d}:{value.minute:02d}"
        await self.coordinator.async_set_start_time(self.zone_id, time_str)
