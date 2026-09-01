# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Service registration for IrriSynk."""

from __future__ import annotations

import logging
import re

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def async_register_services(hass: HomeAssistant) -> None:
    """Register domain services once (guard on the last-added service)."""
    if hass.services.has_service(DOMAIN, "remove_zone_from_cascade"):
        return

    async def _recalculate_zone(call: ServiceCall) -> None:
        zone_id = call.data.get("zone_id")
        for coordinator in hass.data.get(DOMAIN, {}).values():
            if zone_id in coordinator.zone_states:
                await coordinator.async_request_refresh()

    async def _recalculate_all(call: ServiceCall) -> None:
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_request_refresh()

    async def _reload_catalog(call: ServiceCall) -> None:
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_initialize()
            await coordinator.async_request_refresh()

    async def _add_zones(call: ServiceCall) -> None:
        count = int(call.data.get("count", 1))
        entry_id = call.data.get("entry_id")

        entries = hass.config_entries.async_entries(DOMAIN)
        if entry_id:
            entries = [e for e in entries if e.entry_id == entry_id]

        for entry in entries:
            current_zones: list[str] = list(
                entry.options.get("zones", entry.data.get("zones", []))
            )
            highest = 0
            for z in current_zones:
                m = re.match(r"^zone_(\d+)$", z)
                if m:
                    highest = max(highest, int(m.group(1)))

            new_zones = [f"zone_{highest + i + 1}" for i in range(count)]
            updated_options = {**entry.options, "zones": current_zones + new_zones}
            hass.config_entries.async_update_entry(entry, options=updated_options)
            await hass.config_entries.async_reload(entry.entry_id)

    async def _reorder_zones(call: ServiceCall) -> None:
        zone_ids: list[str] = list(call.data.get("zone_ids", []))
        if not zone_ids:
            return
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_reorder_zones(zone_ids)

    async def _reorder_cascade_zones(call: ServiceCall) -> None:
        cascade_id: str = call.data.get("cascade_id", "")
        zone_ids: list[str] = list(call.data.get("zone_ids", []))
        if not cascade_id or not zone_ids:
            return
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_reorder_cascade_zones(cascade_id, zone_ids)

    async def _add_zone_to_cascade(call: ServiceCall) -> None:
        cascade_id: str = call.data.get("cascade_id", "")
        zone_id: str = call.data.get("zone_id", "")
        if not cascade_id or not zone_id:
            return
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_add_zone_to_cascade(cascade_id, zone_id)

    async def _remove_zone_from_cascade(call: ServiceCall) -> None:
        cascade_id: str = call.data.get("cascade_id", "")
        zone_id: str = call.data.get("zone_id", "")
        if not cascade_id or not zone_id:
            return
        for coordinator in hass.data.get(DOMAIN, {}).values():
            await coordinator.async_remove_zone_from_cascade(cascade_id, zone_id)

    hass.services.async_register(DOMAIN, "recalculate_zone", _recalculate_zone)
    hass.services.async_register(DOMAIN, "recalculate_all", _recalculate_all)
    hass.services.async_register(DOMAIN, "reload_kc_catalog", _reload_catalog)
    hass.services.async_register(DOMAIN, "add_zones", _add_zones)
    hass.services.async_register(DOMAIN, "reorder_zones", _reorder_zones)
    hass.services.async_register(DOMAIN, "reorder_cascade_zones", _reorder_cascade_zones)
    hass.services.async_register(DOMAIN, "add_zone_to_cascade", _add_zone_to_cascade)
    hass.services.async_register(DOMAIN, "remove_zone_from_cascade", _remove_zone_from_cascade)
