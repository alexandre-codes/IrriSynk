# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Transient (non-persisted) form state for IrriSynk."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FormState:
    """All transient form attributes of the coordinator — reset to defaults on restart."""

    # Cascade creation form
    cascade_form_name: str = ""
    cascade_form_time: str | None = None

    # Custom cultivation mode form
    cult_mode_form_name: str = ""
    cult_mode_form_et0: float = 1.0

    # Custom crop form
    crop_form_name: str = ""
    crop_form_root_depth: int = 50

    # Add-stage form
    stage_form_crop_id: str = ""
    stage_form_name: str = ""
    stage_form_kc: float = 1.0
    stage_form_duration_open: int = 30
    stage_form_duration_gh: int = 25

    # Stage edit form
    stage_edit_crop_id: str = ""
    stage_edit_stage_id: str = ""
    stage_edit_name: str = ""
    stage_edit_kc: float = 1.0
    stage_edit_duration_open: int = 30
    stage_edit_duration_gh: int = 25

    # Drip calculator inputs
    calc_flow_lh: float = 2.0
    calc_dripper_spacing_cm: float = 30.0
    calc_line_count: float = 4.0
    calc_line_spacing_cm: float = 50.0
    calc_line_length_m: float = 10.0
    calc_zone_width_m: float = 5.0
    calc_result_mm_h: float | None = None
