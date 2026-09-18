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


async def test_cascade_advances_past_a_zone_stopped_overdue_at_reboot(hass, hass_storage):
    """A restart wipes in-memory cascade progress (_cascade_active); recovery must
    restore enough of it that an overdue zone still hands off to the next one,
    instead of the cascade dying silently right there."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_WEATHER_ENTITY_ID: "weather.test",
            CONF_ZONES: ["zone_1", "zone_2"],
            CONF_KC_CATALOG_PATH: "data/kc_catalog.json",
            CONF_LATITUDE: 45.0,
        },
    )
    entry.add_to_hass(hass)

    coord = IrrigationCoordinator(hass, entry)
    await coord.async_initialize()
    coord._async_get_states_batch = AsyncMock(return_value={})
    coord.data = {}
    coord.zone_states = {
        "zone_1": ZoneState(
            zone_id="zone_1", crop_id="tomate", stage_mode="manual",
            cultivation_mode="plein_champ", manual_stage_id="s1",
            zone_mode=ZONE_MODE_SCHEDULED, scheduled_duration_min=10.0,
            switch_entity_id="switch.zone_1", start_time_str="06:00",
            irrigation_end_time=(dt_util.now() - timedelta(minutes=1)).isoformat(),
        ),
        "zone_2": ZoneState(
            zone_id="zone_2", crop_id="tomate", stage_mode="manual",
            cultivation_mode="plein_champ", manual_stage_id="s1",
            zone_mode=ZONE_MODE_SCHEDULED, scheduled_duration_min=10.0,
            switch_entity_id="switch.zone_2",
        ),
    }
    coord.cascades = [
        CascadeGroup(cascade_id="cascade_1", name="Cascade", enabled=True,
                     start_time="06:00", zone_ids=["zone_1", "zone_2"]),
    ]
    # As it would come back from disk after the fix: the sequence mid-run before the restart.
    coord._cascade_active = {"cascade_1": ["zone_1", "zone_2"]}
    hass.states.async_set("switch.zone_1", "on")
    hass.states.async_set("switch.zone_2", "off")
    hass.services.async_register("switch", "turn_on", _noop_turn_on)
    hass.services.async_register("switch", "turn_off", _noop_turn_off)

    await coord._async_recover_irrigation_state()
    await hass.async_block_till_done()

    assert hass.states.get("switch.zone_1").state == "off"
    assert coord._cascade_active["cascade_1"] == ["zone_2"]


async def test_stop_confirmation_retries_and_eventually_alerts(hass, coordinator):
    """turn_off is fire-and-forget; if the valve never actually confirms closing,
    IrriSynk must keep retrying and finally raise an alert instead of trusting
    the first command blindly."""
    async def _dropped_turn_off(call):
        pass  # simulates a lost command: the switch state never changes

    hass.services.async_register("switch", "turn_off", _dropped_turn_off)
    coordinator._async_notify_stop_failed = AsyncMock()

    hass.states.async_set("switch.zone_1", "on")
    coordinator._active_irrigations.add("zone_1")
    coordinator.zone_states["zone_1"] = replace(
        coordinator.zone_states["zone_1"],
        irrigation_end_time=(_at(7, 0) - timedelta(minutes=1)).isoformat(),
    )

    # First tick issues the stop command and starts tracking confirmation.
    await coordinator._async_check_schedule(_at(7, 0))
    await hass.async_block_till_done()
    assert hass.states.get("switch.zone_1").state == "on"  # command was dropped
    assert "zone_1" in coordinator._pending_stop

    for _ in range(15):
        if "zone_1" not in coordinator._pending_stop:
            break
        await coordinator._async_check_schedule(_at(7, 0))
        await hass.async_block_till_done()

    coordinator._async_notify_stop_failed.assert_awaited_once_with("zone_1")
    assert "zone_1" not in coordinator._pending_stop


async def test_stop_confirmation_clears_once_valve_reports_off(hass, coordinator):
    """A late but successful close shouldn't keep retrying or alert."""
    hass.states.async_set("switch.zone_1", "on")
    coordinator._active_irrigations.add("zone_1")
    coordinator.zone_states["zone_1"] = replace(
        coordinator.zone_states["zone_1"],
        irrigation_end_time=(_at(7, 0) - timedelta(minutes=1)).isoformat(),
    )

    await coordinator._async_check_schedule(_at(7, 0))
    await hass.async_block_till_done()
    assert hass.states.get("switch.zone_1").state == "off"
    assert "zone_1" in coordinator._pending_stop  # confirmation hasn't run yet this tick

    # Next tick's confirmation step (step 0) observes the now-off switch and clears it.
    await coordinator._async_check_schedule(_at(7, 1))
    await hass.async_block_till_done()
    assert "zone_1" not in coordinator._pending_stop
