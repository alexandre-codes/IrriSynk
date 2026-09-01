# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Cascade irrigation mixin for IrriSynk coordinator."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import timedelta

from homeassistant.util import dt as dt_util

from .const import DOMAIN, ZONE_MODE_MANUAL, ZONE_MODE_SCHEDULED

_LOGGER = logging.getLogger(__name__)


class CascadeMixin:
    """Mixin providing cascade irrigation group management."""

    def _cascade_valid_zones(self, cascade) -> list[str]:
        """Zones in this cascade with a switch configured and not in manual mode."""
        return [
            z for z in cascade.zone_ids
            if z in self.zone_states
            and self.zone_states[z].switch_entity_id
            and self.zone_states[z].zone_mode != ZONE_MODE_MANUAL
        ]

    def _write_cascade_times(self, zone_ids: list[str], first_hm: str) -> None:
        """Compute and write start_time_str for each zone in cascade sequence."""
        computed = self.data or {}
        h, m = map(int, first_hm.split(":"))
        current = dt_util.now().replace(hour=h, minute=m, second=0, microsecond=0)
        for zone_id in zone_ids:
            self.zone_states[zone_id] = replace(
                self.zone_states[zone_id],
                start_time_str=f"{current.hour:02d}:{current.minute:02d}",
            )
            zone = self.zone_states[zone_id]
            if zone.zone_mode == ZONE_MODE_SCHEDULED:
                duration = zone.scheduled_duration_min
            else:
                duration = getattr(computed.get(zone_id), "recommended_duration_min", 0.0) or 0.0
            current += timedelta(minutes=max(duration, 1.0) + 2)  # +2 min inter-zone delay

    def _refresh_all_cascade_times(self) -> None:
        """Rewrite start_time_str for all enabled cascades."""
        for cascade in self.cascades:
            if cascade.enabled and cascade.start_time:
                self._write_cascade_times(self._cascade_valid_zones(cascade), cascade.start_time)

    async def _async_start_cascade(self, cascade) -> None:
        """Register cascade sequence and schedule only the first zone; subsequent zones
        are scheduled one-by-one as each zone finishes via _async_recalculate_cascade_from."""
        valid = self._cascade_valid_zones(cascade)
        if not valid:
            _LOGGER.warning(
                "Cascade %s (%s): no eligible zones — zone_ids=%s, states=%s",
                cascade.cascade_id, cascade.name, cascade.zone_ids,
                {z: (self.zone_states[z].switch_entity_id, self.zone_states[z].zone_mode)
                 for z in cascade.zone_ids if z in self.zone_states},
            )
            return
        _LOGGER.info("Cascade %s: sequence %s", cascade.cascade_id, valid)
        self._cascade_active[cascade.cascade_id] = valid
        self.zone_states[valid[0]] = replace(
            self.zone_states[valid[0]], start_time_str=cascade.start_time
        )
        await self._async_save()

    async def _async_recalculate_cascade_from(self, finished_zone_id: str) -> None:
        """After a zone finishes, schedule only the immediately next cascade zone."""
        cascade = next((c for c in self.cascades if finished_zone_id in c.zone_ids), None)
        if cascade is None:
            return
        active = self._cascade_active.get(cascade.cascade_id, [])
        if finished_zone_id not in active:
            return
        idx = active.index(finished_zone_id)
        remaining = active[idx + 1:]
        if not remaining:
            self._cascade_active.pop(cascade.cascade_id, None)
            _LOGGER.info("Cascade %s: all zones completed", cascade.cascade_id)
            return
        now = dt_util.now()
        next_start = now + timedelta(minutes=1)
        next_hm = f"{next_start.hour:02d}:{next_start.minute:02d}"
        self._cascade_active[cascade.cascade_id] = remaining
        # Write times for all remaining zones for display accuracy; the guard in
        # _async_check_schedule step 3 ensures only remaining[0] can actually start.
        self._write_cascade_times(remaining, next_hm)
        await self._async_save()
        _LOGGER.info("Cascade %s: next zone %s scheduled at %s", cascade.cascade_id, remaining[0], next_hm)

    async def async_set_cascade_enabled(self, cascade_id: str, enabled: bool) -> None:
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade:
            return
        cascade.enabled = enabled
        if not enabled:
            self._cascade_active.pop(cascade_id, None)
        elif cascade.start_time:
            self._write_cascade_times(self._cascade_valid_zones(cascade), cascade.start_time)
        await self._async_save()
        self._notify_entities()

    async def async_set_cascade_time(self, cascade_id: str, time_str: str | None) -> None:
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade:
            return
        cascade.start_time = time_str
        if cascade.enabled and time_str:
            self._write_cascade_times(self._cascade_valid_zones(cascade), time_str)
        await self._async_save()
        self._notify_entities()

    async def async_set_cascade_form_name(self, name: str) -> None:
        self.forms.cascade_form_name = name
        self._notify_entities()

    async def async_set_cascade_form_time(self, time_str: str | None) -> None:
        self.forms.cascade_form_time = time_str
        self._notify_entities()

    async def async_add_cascade(self) -> None:
        """Create a new cascade group from form state and register its HA entities."""
        from .dashboard import async_update_dashboard
        from .models.domain import CascadeGroup
        existing_ids = {c.cascade_id for c in self.cascades}
        i = len(self.cascades) + 1
        cascade_id = f"cascade_{i}"
        while cascade_id in existing_ids:
            i += 1
            cascade_id = f"cascade_{i}"
        name = self.forms.cascade_form_name.strip() or f"Cascade {i}"
        new_cascade = CascadeGroup(
            cascade_id=cascade_id,
            name=name,
            enabled=False,
            start_time=self.forms.cascade_form_time,
            zone_ids=[],
        )
        self.cascades.append(new_cascade)
        self.forms.cascade_form_name = ""
        self.forms.cascade_form_time = None
        if self._cascades_add_switch_entities:
            from .switch import CascadeGroupSwitch
            self._cascades_add_switch_entities([CascadeGroupSwitch(self, cascade_id)])
        if self._cascades_add_time_entities:
            from .time import CascadeGroupTimeEntity
            self._cascades_add_time_entities([CascadeGroupTimeEntity(self, cascade_id)])
        if self._cascades_add_button_entities:
            from .button import DeleteCascadeButton, AddZoneToCascadeButton
            self._cascades_add_button_entities([
                DeleteCascadeButton(self, cascade_id),
                AddZoneToCascadeButton(self, cascade_id),
            ])
        if self._cascades_add_select_entities:
            from .select import CascadeZoneSelectorSelect
            self._cascades_add_select_entities([CascadeZoneSelectorSelect(self, cascade_id)])
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_remove_cascade(self, cascade_id: str) -> None:
        """Delete a cascade group and remove its HA entities from the registry."""
        from .dashboard import async_update_dashboard
        from homeassistant.helpers import entity_registry as er
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade:
            return
        for zone_id in cascade.zone_ids:
            if zone_id in self.zone_states:
                self.zone_states[zone_id] = replace(self.zone_states[zone_id], start_time_str=None)
        self.cascades.remove(cascade)
        self._cascade_active.pop(cascade_id, None)
        ent_reg = er.async_get(self.hass)
        for platform, uid_suffix in [
            ("switch", f"{cascade_id}_enabled"),
            ("time", f"{cascade_id}_time"),
            ("button", f"{cascade_id}_delete"),
            ("button", f"{cascade_id}_add_zone"),
            ("select", f"{cascade_id}_zone_selector"),
        ]:
            uid = f"{self.entry.entry_id}_cascade_{uid_suffix}"
            eid = ent_reg.async_get_entity_id(platform, DOMAIN, uid)
            if eid:
                ent_reg.async_remove(eid)
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_add_zone_to_cascade(self, cascade_id: str, zone_id: str) -> None:
        """Add a zone to a cascade group; send HA notification if already assigned elsewhere."""
        from homeassistant.components.persistent_notification import async_create as pn_create
        for c in self.cascades:
            if zone_id in c.zone_ids:
                if c.cascade_id == cascade_id:
                    return
                zone_name = self._zone_display_name(zone_id)
                if self._is_english():
                    msg = f"Zone **{zone_name}** is already assigned to cascade **{c.name}**."
                    title = "IrriSynk – Zone already assigned"
                else:
                    msg = f"La zone **{zone_name}** est déjà assignée à la cascade **{c.name}**."
                    title = "IrriSynk – Zone déjà assignée"
                try:
                    result = pn_create(self.hass, msg, title=title, notification_id=f"{DOMAIN}_cascade_conflict")
                    if hasattr(result, "__await__"):
                        await result
                except Exception:  # noqa: BLE001
                    pass
                return
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade or zone_id not in self.zone_states:
            return
        cascade.zone_ids.append(zone_id)
        if cascade.start_time:
            self._write_cascade_times(self._cascade_valid_zones(cascade), cascade.start_time)
        await self._async_save()
        self._notify_entities()
        from .dashboard import async_update_dashboard
        await async_update_dashboard(self.hass)

    async def async_remove_zone_from_cascade(self, cascade_id: str, zone_id: str) -> None:
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade or zone_id not in cascade.zone_ids:
            return
        cascade.zone_ids.remove(zone_id)
        if zone_id in self.zone_states:
            self.zone_states[zone_id] = replace(self.zone_states[zone_id], start_time_str=None)
        await self._async_save()
        self._notify_entities()
        from .dashboard import async_update_dashboard
        await async_update_dashboard(self.hass)

    async def async_reorder_cascade_zones(self, cascade_id: str, zone_ids: list[str]) -> None:
        from .dashboard import async_update_dashboard
        cascade = next((c for c in self.cascades if c.cascade_id == cascade_id), None)
        if not cascade:
            return
        valid = [z for z in zone_ids if z in cascade.zone_ids]
        tail = [z for z in cascade.zone_ids if z not in valid]
        cascade.zone_ids = valid + tail
        if cascade.start_time:
            self._write_cascade_times(self._cascade_valid_zones(cascade), cascade.start_time)
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)
