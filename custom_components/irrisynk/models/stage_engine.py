# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Growth stage resolution logic."""

from __future__ import annotations

from datetime import date

from ..const import CULTIVATION_MODES_GREENHOUSE
from .domain import CropDefinition, StageDefinition


def _stage_duration(stage: StageDefinition, cultivation_mode: str) -> int | None:
    if cultivation_mode in CULTIVATION_MODES_GREENHOUSE:
        return stage.duration_days_greenhouse or stage.duration_days
    return stage.duration_days_open_field or stage.duration_days


def resolve_stage_auto(
    crop: CropDefinition, planting_date: date | None, today: date, cultivation_mode: str
) -> StageDefinition:
    """Resolve current stage using planting date and stage durations."""
    if planting_date is None:
        return crop.stages[0]

    day_index = max(0, (today - planting_date).days)
    consumed = 0

    for stage in crop.stages:
        stage_duration = _stage_duration(stage, cultivation_mode)
        if stage_duration is None:
            return stage
        if day_index < consumed + stage_duration:
            return stage
        consumed += stage_duration

    return crop.stages[-1]


def resolve_stage_manual(crop: CropDefinition, stage_id: str) -> StageDefinition:
    """Resolve stage by selected stage_id, fallback to first."""
    for stage in crop.stages:
        if stage.stage_id == stage_id:
            return stage
    return crop.stages[0]


def resolve_stage_index(
    crop: CropDefinition, planting_date: date | None, today: date, cultivation_mode: str
) -> int:
    """Return 0-based index of the current stage (used for progressive root depth)."""
    if planting_date is None:
        return 0
    day_index = max(0, (today - planting_date).days)
    consumed = 0
    for i, stage in enumerate(crop.stages):
        stage_duration = _stage_duration(stage, cultivation_mode)
        if stage_duration is None:
            return i
        if day_index < consumed + stage_duration:
            return i
        consumed += stage_duration
    return len(crop.stages) - 1
