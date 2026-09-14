# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Diagnostics support for IrriSynk."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_LATITUDE, DOMAIN
from .coordinator import IrrigationCoordinator

TO_REDACT = {CONF_LATITUDE, "telegram_chat_id", "notify_ha_service"}


def _jsonable(data: Any) -> Any:
    """Coerce dataclasses/dates/etc. into plain JSON-safe types."""
    return json.loads(json.dumps(data, default=str))


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: IrrigationCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator": {
            "et0_mm": coordinator.et0_mm,
            "rain_mm_today": coordinator.rain_mm_today,
            "forecast_tmin_c": coordinator.forecast_tmin_c,
            "global_pause_enabled": coordinator.global_pause_enabled,
            "frost_protection_enabled": coordinator.frost_protection_enabled,
            "frost_threshold_c": coordinator.frost_threshold_c,
            "telegram_enabled": coordinator.telegram_enabled,
            "telegram_notify_irrigations": coordinator.telegram_notify_irrigations,
            "telegram_notify_unavailable": coordinator.telegram_notify_unavailable,
            "notify_ha_enabled": coordinator.notify_ha_enabled,
            "active_irrigations": sorted(coordinator._active_irrigations),
            "cascade_active": coordinator._cascade_active,
        },
        "zones": _jsonable(
            {zid: asdict(z) for zid, z in coordinator.zone_states.items()}
        ),
        "computed_data": _jsonable(
            {zid: asdict(v) for zid, v in (coordinator.data or {}).items()}
        ),
        "cascades": _jsonable([asdict(c) for c in coordinator.cascades]),
        "custom_cultivation_modes": _jsonable(
            [asdict(m) for m in coordinator.custom_cultivation_modes]
        ),
        "custom_crops": _jsonable(
            [asdict(c) for c in coordinator.custom_crops]
        ),
    }
