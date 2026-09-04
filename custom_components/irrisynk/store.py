# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Persistent storage for IrriSynk."""

from __future__ import annotations

import logging
from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import CULTIVATION_MODE_OPEN_FIELD, DOMAIN, ZONE_MODE_AUTO, ZONE_MODE_MANUAL
from .models.domain import CascadeGroup, CustomCropDefinition, CustomCultivationMode, CustomStageDefinition, ZoneState

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_store"


class IrrigationStore:
    """Storage wrapper."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)

    async def async_load(self) -> tuple[dict[str, ZoneState], list[CascadeGroup], list[CustomCultivationMode], list[CustomCropDefinition], dict]:
        """Load zone states, cascade groups, and custom cultivation modes from disk."""
        payload = await self._store.async_load() or {}
        zones = payload.get("zones", {})
        zone_order: list[str] = payload.get("zone_order", list(zones.keys()))
        ordered_ids = [z for z in zone_order if z in zones] + [z for z in zones if z not in zone_order]
        result: dict[str, ZoneState] = {}
        for zone_id in ordered_ids:
            raw = zones[zone_id]
            planting_date = (
                date.fromisoformat(raw["planting_date"]) if raw.get("planting_date") else None
            )
            cultivation_mode = raw.get("cultivation_mode", CULTIVATION_MODE_OPEN_FIELD)
            if cultivation_mode == "serre":  # migrate legacy generic greenhouse → serre_ete
                cultivation_mode = "serre_ete"
            frequency_anchor_date = (
                date.fromisoformat(raw["frequency_anchor_date"]) if raw.get("frequency_anchor_date") else None
            )
            result[zone_id] = ZoneState(
                zone_id=zone_id,
                crop_id=raw["crop_id"],
                stage_mode=raw["stage_mode"],
                cultivation_mode=cultivation_mode,
                manual_stage_id=raw["manual_stage_id"],
                planting_date=planting_date,
                zone_mode=raw.get("zone_mode") or (
                    ZONE_MODE_AUTO if raw.get("auto_mode_enabled", True) else ZONE_MODE_MANUAL
                ),
                scheduled_duration_min=raw.get("scheduled_duration_min", 30.0),
                max_duration_min=raw.get("max_duration_min", 60.0),
                et0_correction_factor=raw.get("et0_correction_factor", 1.0),
                rain_effectiveness_pct=raw.get("rain_effectiveness_pct", 80.0),
                soil_buffer_mm=raw.get("soil_buffer_mm", 0.0),
                flow_mm_h=raw.get("flow_mm_h", 5.0),
                switch_entity_id=raw.get("switch_entity_id") or None,
                start_time_str=raw.get("start_time_str") or None,
                soil_water_balance_mm=raw.get("soil_water_balance_mm", 0.0),
                irrigation_end_time=raw.get("irrigation_end_time") or None,
                soil_type=raw.get("soil_type", "loam"),
                frequency_days=int(raw.get("frequency_days", 1)),
                frequency_anchor_date=frequency_anchor_date,
            )
        # Load cascade groups — migrate from legacy single-cascade format if needed
        if "cascades" in payload:
            cascades: list[CascadeGroup] = [
                CascadeGroup(
                    cascade_id=c["cascade_id"],
                    name=c.get("name", c["cascade_id"]),
                    enabled=c.get("enabled", False),
                    start_time=c.get("start_time") or None,
                    zone_ids=[z for z in c.get("zone_ids", []) if z in zones],
                )
                for c in payload["cascades"]
                if isinstance(c, dict) and "cascade_id" in c
            ]
        elif "cascade" in payload:
            old = payload["cascade"]
            cascades = [CascadeGroup(
                cascade_id="cascade_1",
                name="Cascade",
                enabled=old.get("enabled", False),
                start_time=old.get("start_time") or None,
                zone_ids=[z for z in old.get("zone_ids", ordered_ids) if z in zones],
            )]
        else:
            cascades = []

        # Guard: remove zone_ids assigned to more than one cascade (keep first occurrence)
        _seen: set[str] = set()
        for _c in cascades:
            _c.zone_ids = [z for z in _c.zone_ids if z not in _seen]
            _seen.update(_c.zone_ids)

        raw_modes = payload.get("custom_cultivation_modes", [])
        custom_modes = [
            CustomCultivationMode(name=m["name"], et0_factor=float(m["et0_factor"]))
            for m in raw_modes
            if isinstance(m, dict) and "name" in m and "et0_factor" in m
        ]
        raw_custom_crops = payload.get("custom_crops", [])
        custom_crops: list[CustomCropDefinition] = []
        for rc in raw_custom_crops:
            if not isinstance(rc, dict) or "crop_id" not in rc or "name" not in rc:
                continue
            stages = [
                CustomStageDefinition(
                    stage_id=s["stage_id"],
                    label=s["label"],
                    kc=float(s["kc"]),
                    duration_days_open_field=int(s.get("duration_days_open_field", 0)),
                    duration_days_greenhouse=int(s.get("duration_days_greenhouse", 0)),
                )
                for s in rc.get("stages", [])
                if isinstance(s, dict) and "stage_id" in s and "label" in s
            ]
            custom_crops.append(CustomCropDefinition(
                crop_id=rc["crop_id"],
                name=rc["name"],
                stages=stages,
                root_depth_cm=int(rc.get("root_depth_cm", 50)),
            ))
        telegram = payload.get("telegram", {})
        return result, cascades, custom_modes, custom_crops, telegram

    async def async_save(
        self,
        zones: dict[str, ZoneState],
        cascades: list[CascadeGroup] | None = None,
        custom_cultivation_modes: list[CustomCultivationMode] | None = None,
        custom_crops: list[CustomCropDefinition] | None = None,
        telegram_enabled: bool = False,
        telegram_chat_id: str = "",
        telegram_notify_irrigations: bool = True,
        telegram_notify_unavailable: bool = True,
    ) -> None:
        """Save zone states, cascade groups, custom cultivation modes, and telegram config to disk."""
        payload = {
            "cascades": [
                {
                    "cascade_id": c.cascade_id,
                    "name": c.name,
                    "enabled": c.enabled,
                    "start_time": c.start_time,
                    "zone_ids": c.zone_ids,
                }
                for c in (cascades or [])
            ],
            "telegram": {
                "enabled": telegram_enabled,
                "chat_id": telegram_chat_id,
                "notify_irrigations": telegram_notify_irrigations,
                "notify_unavailable": telegram_notify_unavailable,
            },
            "custom_cultivation_modes": [
                {"name": m.name, "et0_factor": m.et0_factor}
                for m in (custom_cultivation_modes or [])
            ],
            "custom_crops": [
                {
                    "crop_id": c.crop_id,
                    "name": c.name,
                    "root_depth_cm": c.root_depth_cm,
                    "stages": [
                        {
                            "stage_id": s.stage_id,
                            "label": s.label,
                            "kc": s.kc,
                            "duration_days_open_field": s.duration_days_open_field,
                            "duration_days_greenhouse": s.duration_days_greenhouse,
                        }
                        for s in c.stages
                    ],
                }
                for c in (custom_crops or [])
            ],
            "zone_order": list(zones.keys()),
            "zones": {
                zone_id: {
                    "crop_id": zone.crop_id,
                    "stage_mode": zone.stage_mode,
                    "cultivation_mode": zone.cultivation_mode,
                    "manual_stage_id": zone.manual_stage_id,
                    "planting_date": zone.planting_date.isoformat() if zone.planting_date else None,
                    "zone_mode": zone.zone_mode,
                    "scheduled_duration_min": zone.scheduled_duration_min,
                    "max_duration_min": zone.max_duration_min,
                    "et0_correction_factor": zone.et0_correction_factor,
                    "rain_effectiveness_pct": zone.rain_effectiveness_pct,
                    "soil_buffer_mm": zone.soil_buffer_mm,
                    "flow_mm_h": zone.flow_mm_h,
                    "switch_entity_id": zone.switch_entity_id,
                    "start_time_str": zone.start_time_str,
                    "soil_water_balance_mm": zone.soil_water_balance_mm,
                    "irrigation_end_time": zone.irrigation_end_time,
                    "soil_type": zone.soil_type,
                    "frequency_days": zone.frequency_days,
                    "frequency_anchor_date": (
                        zone.frequency_anchor_date.isoformat() if zone.frequency_anchor_date else None
                    ),
                }
                for zone_id, zone in zones.items()
            }
        }
        await self._store.async_save(payload)
