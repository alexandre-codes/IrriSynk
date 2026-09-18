# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Tests for IrrigationStore persistence and legacy-data migrations."""

from __future__ import annotations

from typing import Any

from custom_components.irrisynk.models.domain import ZoneState
from custom_components.irrisynk.store import IrrigationStore, STORAGE_KEY

_MINIMAL_ZONE_RAW: dict[str, Any] = {
    "crop_id": "tomate",
    "stage_mode": "manual",
    "cultivation_mode": "plein_champ",
    "manual_stage_id": "s1",
}


def _seed(hass_storage: dict[str, Any], data: dict[str, Any]) -> None:
    hass_storage[STORAGE_KEY] = {"version": 1, "data": data}


async def test_load_empty_store_returns_defaults(hass, hass_storage):
    store = IrrigationStore(hass)
    zones, cascades, modes, crops, telegram, global_cfg, cascade_active = await store.async_load()
    assert zones == {}
    assert cascades == []
    assert modes == []
    assert crops == []
    assert telegram == {}
    assert global_cfg == {}
    assert cascade_active == {}


async def test_legacy_greenhouse_mode_is_migrated(hass, hass_storage):
    _seed(hass_storage, {
        "zones": {"zone_1": {**_MINIMAL_ZONE_RAW, "cultivation_mode": "serre"}},
        "zone_order": ["zone_1"],
    })
    store = IrrigationStore(hass)
    zones, *_ = await store.async_load()
    assert zones["zone_1"].cultivation_mode == "serre_ete"


async def test_legacy_single_cascade_is_migrated_to_list(hass, hass_storage):
    _seed(hass_storage, {
        "zones": {"zone_1": dict(_MINIMAL_ZONE_RAW), "zone_2": dict(_MINIMAL_ZONE_RAW)},
        "zone_order": ["zone_1", "zone_2"],
        "cascade": {"enabled": True, "start_time": "06:00", "zone_ids": ["zone_1", "zone_2"]},
    })
    store = IrrigationStore(hass)
    zones, cascades, *_ = await store.async_load()
    assert len(cascades) == 1
    assert cascades[0].cascade_id == "cascade_1"
    assert cascades[0].enabled is True
    assert cascades[0].start_time == "06:00"
    assert cascades[0].zone_ids == ["zone_1", "zone_2"]


async def test_cascade_zone_referencing_deleted_zone_is_dropped(hass, hass_storage):
    _seed(hass_storage, {
        "zones": {"zone_1": dict(_MINIMAL_ZONE_RAW)},
        "zone_order": ["zone_1"],
        "cascades": [{
            "cascade_id": "cascade_1", "name": "Cascade", "enabled": False,
            "start_time": None, "zone_ids": ["zone_1", "zone_ghost"],
        }],
    })
    store = IrrigationStore(hass)
    _, cascades, *_ = await store.async_load()
    assert cascades[0].zone_ids == ["zone_1"]


async def test_zone_in_two_cascades_is_kept_only_in_the_first(hass, hass_storage):
    _seed(hass_storage, {
        "zones": {"zone_1": dict(_MINIMAL_ZONE_RAW), "zone_2": dict(_MINIMAL_ZONE_RAW)},
        "zone_order": ["zone_1", "zone_2"],
        "cascades": [
            {"cascade_id": "cascade_1", "name": "A", "enabled": False, "start_time": None,
             "zone_ids": ["zone_1", "zone_2"]},
            {"cascade_id": "cascade_2", "name": "B", "enabled": False, "start_time": None,
             "zone_ids": ["zone_2"]},
        ],
    })
    store = IrrigationStore(hass)
    _, cascades, *_ = await store.async_load()
    assert cascades[0].zone_ids == ["zone_1", "zone_2"]
    assert cascades[1].zone_ids == []  # zone_2 already claimed by cascade_1


async def test_save_then_load_round_trip_preserves_global_config(hass, hass_storage):
    store = IrrigationStore(hass)
    await store.async_save(
        zones={},
        global_pause_enabled=True,
        frost_protection_enabled=True,
        frost_threshold_c=1.5,
        notify_ha_enabled=True,
        notify_ha_service="notify.mobile_app_test",
    )
    _, _, _, _, _, global_cfg, _ = await store.async_load()
    assert global_cfg == {
        "global_pause_enabled": True,
        "frost_protection_enabled": True,
        "frost_threshold_c": 1.5,
        "notify_ha_enabled": True,
        "notify_ha_service": "notify.mobile_app_test",
    }


async def test_cascade_active_round_trips_and_drops_unknown_zones(hass, hass_storage):
    store = IrrigationStore(hass)
    zone = ZoneState(
        zone_id="zone_1", crop_id="tomate", stage_mode="manual",
        cultivation_mode="plein_champ", manual_stage_id="s1",
    )
    await store.async_save(
        zones={"zone_1": zone},
        cascade_active={"cascade_1": ["zone_1", "zone_ghost"], "cascade_2": []},
    )
    *_, cascade_active = await store.async_load()
    # zone_ghost isn't a known zone so it's dropped from the sequence; cascade_2's
    # already-empty sequence is dropped entirely rather than kept as a stale entry.
    assert cascade_active == {"cascade_1": ["zone_1"]}
