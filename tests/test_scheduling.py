# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Scheduler tests: normal zone start, global pause, and frost protection gates."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.irrisynk.const import (
    CONF_KC_CATALOG_PATH,
    CONF_LATITUDE,
    CONF_WEATHER_ENTITY_ID,
    CONF_ZONES,
    DOMAIN,
    ZONE_MODE_SCHEDULED,
)
from custom_components.irrisynk.coordinator import IrrigationCoordinator
from custom_components.irrisynk.models.domain import CascadeGroup, ZoneState


async def _noop_turn_on(call):
    call.hass.states.async_set(call.data["entity_id"], "on")


async def _noop_turn_off(call):
    call.hass.states.async_set(call.data["entity_id"], "off")


@pytest.fixture
async def coordinator(hass, hass_storage):
    """A coordinator with one SCHEDULED zone, ready for scheduler ticks."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_WEATHER_ENTITY_ID: "weather.test",
            CONF_ZONES: ["zone_1"],
            CONF_KC_CATALOG_PATH: "data/kc_catalog.json",
            CONF_LATITUDE: 45.0,
        },
    )
    entry.add_to_hass(hass)

    coord = IrrigationCoordinator(hass, entry)
    await coord.async_initialize()  # loads the real Kc catalog (needed by crop lookups)
    # Recorder isn't set up in these tests; the recompute-after-stop path only
    # uses this for the "irrigation applied today" stat, irrelevant here.
    coord._async_get_states_batch = AsyncMock(return_value={})
    coord.zone_states = {
        "zone_1": ZoneState(
            zone_id="zone_1",
            crop_id="tomate",
            stage_mode="manual",
            cultivation_mode="plein_champ",
            manual_stage_id="s1",
            zone_mode=ZONE_MODE_SCHEDULED,
            scheduled_duration_min=10.0,
            switch_entity_id="switch.zone_1",
            start_time_str="06:00",
        ),
    }
    coord.data = {}
    hass.states.async_set("switch.zone_1", "off")
    hass.services.async_register("switch", "turn_on", _noop_turn_on)
    hass.services.async_register("switch", "turn_off", _noop_turn_off)
    return coord


def _at(hour: int, minute: int):
    return dt_util.now().replace(hour=hour, minute=minute, second=0, microsecond=0)


async def test_zone_starts_within_its_window(hass, coordinator):
    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert "zone_1" in coordinator._active_irrigations
    assert hass.states.get("switch.zone_1").state == "on"


async def test_global_pause_blocks_new_starts(hass, coordinator):
    coordinator.global_pause_enabled = True

    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert "zone_1" not in coordinator._active_irrigations
    assert hass.states.get("switch.zone_1").state == "off"


async def test_global_pause_does_not_interrupt_a_running_irrigation(hass, coordinator):
    # Zone already running, past its end time (relative to the tick's own clock) —
    # must still be stopped even while paused.
    tick = _at(6, 5)
    coordinator._active_irrigations.add("zone_1")
    past_end = tick - timedelta(minutes=1)
    coordinator.zone_states["zone_1"] = replace(
        coordinator.zone_states["zone_1"], irrigation_end_time=past_end.isoformat()
    )
    hass.states.async_set("switch.zone_1", "on")
    coordinator.global_pause_enabled = True

    await coordinator._async_check_schedule(tick)
    await hass.async_block_till_done()

    assert "zone_1" not in coordinator._active_irrigations
    assert hass.states.get("switch.zone_1").state == "off"


async def test_frost_protection_blocks_start_below_threshold(hass, coordinator):
    coordinator.frost_protection_enabled = True
    coordinator.frost_threshold_c = 2.0
    coordinator.forecast_tmin_c = 0.0  # at/below threshold -> protected

    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert "zone_1" not in coordinator._active_irrigations
    assert hass.states.get("switch.zone_1").state == "off"


async def test_frost_protection_allows_start_above_threshold(hass, coordinator):
    coordinator.frost_protection_enabled = True
    coordinator.frost_threshold_c = 2.0
    coordinator.forecast_tmin_c = 10.0  # comfortably above threshold -> not protected

    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert "zone_1" in coordinator._active_irrigations
    assert hass.states.get("switch.zone_1").state == "on"


async def test_frost_protection_inactive_without_forecast_data(hass, coordinator):
    # No forecast_tmin_c yet (None) -> fail-open, irrigation proceeds normally.
    coordinator.frost_protection_enabled = True
    coordinator.frost_threshold_c = 2.0
    coordinator.forecast_tmin_c = None

    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert "zone_1" in coordinator._active_irrigations


async def test_global_pause_blocks_cascade_start(hass, coordinator):
    coordinator.cascades = [
        CascadeGroup(
            cascade_id="cascade_1", name="Cascade", enabled=True,
            start_time="06:00", zone_ids=["zone_1"],
        )
    ]
    coordinator.global_pause_enabled = True

    await coordinator._async_check_schedule(_at(6, 0))
    await hass.async_block_till_done()

    assert coordinator._cascade_active == {}
