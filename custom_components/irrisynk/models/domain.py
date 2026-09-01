# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Domain models for IrriSynk."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class StageDefinition:
    """One growth stage for a crop."""

    stage_id: str
    label: str
    label_en: str | None
    duration_days: int | None
    duration_days_open_field: int | None
    duration_days_greenhouse: int | None
    kc: float


@dataclass(frozen=True)
class CropDefinition:
    """Crop definition containing its stage list."""

    crop_id: str
    label: str
    label_en: str | None
    stages: tuple[StageDefinition, ...]
    root_depth_cm: int | None = None


@dataclass(frozen=True)
class KcCatalog:
    """Full crop catalog."""

    version: int
    crops: tuple[CropDefinition, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_crop_map", {c.crop_id: c for c in self.crops})

    @property
    def crop_map(self) -> dict[str, CropDefinition]:
        return self._crop_map  # type: ignore[attr-defined]


@dataclass
class ZoneState:
    """Runtime zone state persisted in storage."""

    zone_id: str
    crop_id: str
    stage_mode: str
    cultivation_mode: str
    manual_stage_id: str
    planting_date: date | None = None
    zone_mode: str = "auto"
    scheduled_duration_min: float = 30.0
    max_duration_min: float = 60.0
    et0_correction_factor: float = 1.0
    rain_effectiveness_pct: float = 80.0
    soil_buffer_mm: float = 0.0
    flow_mm_h: float = 5.0
    switch_entity_id: str | None = None
    start_time_str: str | None = None  # "HH:MM"
    soil_water_balance_mm: float = 0.0  # J-1 balance: positive=surplus, negative=deficit
    irrigation_end_time: str | None = None  # ISO datetime — persisted so timer survives reboot
    soil_type: str = "loam"  # FAO-56 soil texture class


@dataclass
class CustomStageDefinition:
    """One growth stage inside a user-defined crop."""

    stage_id: str
    label: str
    kc: float
    duration_days_open_field: int
    duration_days_greenhouse: int

    def to_stage_definition(self) -> "StageDefinition":
        dur_open = self.duration_days_open_field or None
        dur_gh = self.duration_days_greenhouse or None
        return StageDefinition(
            stage_id=self.stage_id,
            label=self.label,
            label_en=None,
            duration_days=dur_open,
            duration_days_open_field=dur_open,
            duration_days_greenhouse=dur_gh,
            kc=self.kc,
        )


@dataclass
class CustomCropDefinition:
    """User-defined crop with its growth stages."""

    crop_id: str
    name: str
    stages: list[CustomStageDefinition]
    root_depth_cm: int = 50

    def to_crop_definition(self) -> "CropDefinition":
        return CropDefinition(
            crop_id=self.crop_id,
            label=self.name,
            label_en=None,
            stages=tuple(s.to_stage_definition() for s in self.stages),
            root_depth_cm=self.root_depth_cm,
        )


@dataclass
class CustomCultivationMode:
    """User-defined cultivation mode with its ET0 correction factor."""

    name: str
    et0_factor: float


@dataclass
class ZoneComputedState:
    """Computed values exposed via sensors."""

    current_stage_id: str
    current_stage_label: str
    kc_current: float
    water_need_mm: float
    recommended_duration_min: float
    effective_duration_min: float
    effective_rain_mm: float
    confidence: int
    soil_water_balance_mm: float = 0.0
    irrigation_today_mm: float = 0.0
    soil_capacity_mm: float = 0.0  # RAW = 0.4 × TAW, computed from soil_type × root_depth
    notes: list[str] = field(default_factory=list)


@dataclass
class CascadeGroup:
    """A named cascade group with an ordered list of zones."""

    cascade_id: str
    name: str
    enabled: bool = False
    start_time: str | None = None  # "HH:MM"
    zone_ids: list[str] = field(default_factory=list)
