# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Pure-function tests for FAO-56 irrigation math (no Home Assistant required)."""

from __future__ import annotations

from datetime import date

from custom_components.irrisynk.models.domain import CropDefinition, StageDefinition
from custom_components.irrisynk.models.irrigation_math import (
    compute_et0_fao56,
    compute_water_need_mm,
    mm_to_minutes,
)
from custom_components.irrisynk.models.stage_engine import (
    resolve_stage_auto,
    resolve_stage_index,
    resolve_stage_manual,
)


def test_et0_fao56_is_non_negative_and_reasonable():
    et0 = compute_et0_fao56(
        tmax_c=25.0, tmin_c=13.0, wind_kmh=7.2,
        pressure_hpa=1013.0, cloud_cover_pct=40.0,
        latitude_deg=45.0, doy=180,
    )
    assert et0 >= 0.0
    # Sanity range for a mild summer day — catches gross unit/formula errors
    assert 1.0 < et0 < 10.0


def test_et0_fao56_increases_with_temperature():
    cool = compute_et0_fao56(
        tmax_c=18.0, tmin_c=8.0, wind_kmh=7.2,
        pressure_hpa=1013.0, cloud_cover_pct=40.0,
        latitude_deg=45.0, doy=180,
    )
    hot = compute_et0_fao56(
        tmax_c=35.0, tmin_c=20.0, wind_kmh=7.2,
        pressure_hpa=1013.0, cloud_cover_pct=40.0,
        latitude_deg=45.0, doy=180,
    )
    assert hot > cool


def test_water_need_mm_basic():
    # ET0=5, Kc=1 -> demand 5mm, minus 2mm effective rain -> 3mm
    assert compute_water_need_mm(5.0, 1.0, 2.0, 0.0) == 3.0


def test_water_need_mm_never_negative():
    # Rain alone exceeds demand -> clamped to 0, not negative
    assert compute_water_need_mm(2.0, 1.0, 10.0, 0.0) == 0.0


def test_water_need_mm_surplus_balance_reduces_need():
    # A positive J-1 balance (surplus) reduces today's need
    need_no_balance = compute_water_need_mm(5.0, 1.0, 0.0, 0.0, soil_water_balance_mm=0.0)
    need_with_surplus = compute_water_need_mm(5.0, 1.0, 0.0, 0.0, soil_water_balance_mm=2.0)
    assert need_with_surplus == need_no_balance - 2.0


def test_water_need_mm_deficit_balance_increases_need():
    # A negative J-1 balance (deficit) increases today's need
    need_no_balance = compute_water_need_mm(5.0, 1.0, 0.0, 0.0, soil_water_balance_mm=0.0)
    need_with_deficit = compute_water_need_mm(5.0, 1.0, 0.0, 0.0, soil_water_balance_mm=-2.0)
    assert need_with_deficit == need_no_balance + 2.0


def test_mm_to_minutes_basic():
    # 10mm need at 5mm/h flow -> 120 minutes
    assert mm_to_minutes(10.0, 5.0) == 120.0


def test_mm_to_minutes_zero_flow_is_safe():
    # A zero/negative flow must not raise (division by zero)
    assert mm_to_minutes(10.0, 0.0) == 0.0
    assert mm_to_minutes(10.0, -1.0) == 0.0


def _crop(stages: list[StageDefinition]) -> CropDefinition:
    return CropDefinition(
        crop_id="test_crop", label="Test", label_en="Test",
        stages=tuple(stages),
    )


def _stage(stage_id: str, days_open: int | None, days_gh: int | None, kc: float) -> StageDefinition:
    return StageDefinition(
        stage_id=stage_id, label=stage_id, label_en=stage_id,
        duration_days=days_open, duration_days_open_field=days_open,
        duration_days_greenhouse=days_gh, kc=kc,
    )


def test_resolve_stage_manual_returns_selected_stage():
    crop = _crop([_stage("s1", 10, 10, 0.5), _stage("s2", 20, 20, 1.0)])
    assert resolve_stage_manual(crop, "s2").stage_id == "s2"


def test_resolve_stage_manual_falls_back_to_first_on_unknown_id():
    crop = _crop([_stage("s1", 10, 10, 0.5), _stage("s2", 20, 20, 1.0)])
    assert resolve_stage_manual(crop, "does_not_exist").stage_id == "s1"


def test_resolve_stage_auto_without_planting_date_returns_first_stage():
    crop = _crop([_stage("s1", 10, 10, 0.5), _stage("s2", 20, 20, 1.0)])
    stage = resolve_stage_auto(crop, None, date(2026, 6, 1), "plein_champ")
    assert stage.stage_id == "s1"


def test_resolve_stage_auto_advances_through_stages_by_day_count():
    crop = _crop([_stage("s1", 10, 10, 0.5), _stage("s2", 20, 20, 1.0), _stage("s3", 15, 15, 0.8)])
    planting = date(2026, 1, 1)

    # Day 5 -> still within stage 1 (0-9)
    assert resolve_stage_auto(crop, planting, date(2026, 1, 6), "plein_champ").stage_id == "s1"
    # Day 15 -> within stage 2 (10-29)
    assert resolve_stage_auto(crop, planting, date(2026, 1, 16), "plein_champ").stage_id == "s2"
    # Day 40 -> within stage 3 (30-44)
    assert resolve_stage_auto(crop, planting, date(2026, 2, 10), "plein_champ").stage_id == "s3"
    # Past the last stage's duration -> stays on the last stage
    assert resolve_stage_auto(crop, planting, date(2026, 12, 31), "plein_champ").stage_id == "s3"


def test_resolve_stage_auto_uses_greenhouse_durations_in_greenhouse_mode():
    # Greenhouse duration for stage 1 is much shorter than open-field
    crop = _crop([_stage("s1", 30, 5, 0.5), _stage("s2", 30, 30, 1.0)])
    planting = date(2026, 1, 1)
    day_index = date(2026, 1, 10)  # day 9 — past greenhouse duration (5) but not open-field (30)

    assert resolve_stage_auto(crop, planting, day_index, "plein_champ").stage_id == "s1"
    assert resolve_stage_auto(crop, planting, day_index, "serre_hiver").stage_id == "s2"


def test_resolve_stage_index_matches_resolve_stage_auto():
    crop = _crop([_stage("s1", 10, 10, 0.5), _stage("s2", 20, 20, 1.0)])
    planting = date(2026, 1, 1)
    today = date(2026, 1, 16)
    stage = resolve_stage_auto(crop, planting, today, "plein_champ")
    idx = resolve_stage_index(crop, planting, today, "plein_champ")
    assert crop.stages[idx].stage_id == stage.stage_id
