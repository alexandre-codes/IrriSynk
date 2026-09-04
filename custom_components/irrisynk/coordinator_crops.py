# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Crops and cultivation modes mixin for IrriSynk coordinator."""

from __future__ import annotations

import logging
from dataclasses import replace

from .const import (
    CULTIVATION_MODE_ET0_FACTORS,
    CULTIVATION_MODE_OPEN_FIELD,
    DEFAULT_ET0_CORRECTION_OPEN_FIELD,
    DOMAIN,
)
from .models.domain import CustomCropDefinition, CustomStageDefinition
from .models.stage_engine import resolve_stage_manual

_LOGGER = logging.getLogger(__name__)


class CropsMixin:
    """Mixin providing crops, stages and cultivation modes management."""

    # ------------------------------------------------------------------
    # Cultivation modes
    # ------------------------------------------------------------------

    def cultivation_mode_options(self) -> list[str]:
        """All available cultivation mode IDs: built-in + custom (name = ID)."""
        from .const import CULTIVATION_MODES
        return CULTIVATION_MODES + [m.name for m in self.custom_cultivation_modes]

    async def async_set_cultivation_mode(self, zone_id: str, cultivation_mode: str) -> None:
        if cultivation_mode in CULTIVATION_MODE_ET0_FACTORS:
            default_factor = CULTIVATION_MODE_ET0_FACTORS[cultivation_mode]
        else:
            custom = next(
                (m for m in self.custom_cultivation_modes if m.name == cultivation_mode), None
            )
            default_factor = custom.et0_factor if custom else DEFAULT_ET0_CORRECTION_OPEN_FIELD
        self.zone_states[zone_id] = replace(
            self.zone_states[zone_id],
            cultivation_mode=cultivation_mode,
            et0_correction_factor=default_factor,
        )
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_add_cultivation_mode(self) -> None:
        """Validate form inputs, add a new custom cultivation mode, and create its delete button."""
        from .dashboard import async_update_dashboard
        from .models.domain import CustomCultivationMode
        name = self.forms.cult_mode_form_name.strip()
        if not name:
            return
        if any(m.name == name for m in self.custom_cultivation_modes):
            return  # duplicate — silently ignore
        self.custom_cultivation_modes.append(
            CustomCultivationMode(name=name, et0_factor=self.forms.cult_mode_form_et0)
        )
        self.forms.cult_mode_form_name = ""
        await self._async_save()
        if self._cult_modes_add_button_entities is not None:
            from .button import DeleteCultModeButton
            self._cult_modes_add_button_entities([DeleteCultModeButton(self, name)])
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_delete_cultivation_mode(self, mode_name: str) -> None:
        """Remove a custom cultivation mode and its delete button entity."""
        from .dashboard import async_update_dashboard
        from homeassistant.helpers import entity_registry as er
        self.custom_cultivation_modes = [
            m for m in self.custom_cultivation_modes if m.name != mode_name
        ]
        # Reset zones that were using this mode to open field
        for zone_id, zone in self.zone_states.items():
            if zone.cultivation_mode == mode_name:
                self.zone_states[zone_id] = replace(
                    zone,
                    cultivation_mode=CULTIVATION_MODE_OPEN_FIELD,
                    et0_correction_factor=DEFAULT_ET0_CORRECTION_OPEN_FIELD,
                )
        # Remove the delete button entity from the entity registry
        ent_reg = er.async_get(self.hass)
        unique_id = f"{self.entry.entry_id}_cult_modes_delete_{mode_name}"
        entity_id = ent_reg.async_get_entity_id("button", DOMAIN, unique_id)
        if entity_id:
            ent_reg.async_remove(entity_id)
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    # ------------------------------------------------------------------
    # Crop helpers
    # ------------------------------------------------------------------

    def crop_options(self) -> list[str]:
        return sorted(self._crop_label(c) for c in self.catalog.crops) + self._custom_crop_options()

    def crop_current_option(self, zone_id: str) -> str:
        crop_id = self.zone_states[zone_id].crop_id
        if crop_id in self.catalog.crop_map:
            return self._crop_label(self.catalog.crop_map[crop_id])
        for custom in self.custom_crops:
            if custom.crop_id == crop_id:
                return custom.name
        return self._crop_label(self.catalog.crops[0])

    def crop_option_to_id(self, option: str) -> str:
        for crop in self.catalog.crops:
            if self._crop_label(crop) == option:
                return crop.crop_id
        for custom in self.custom_crops:
            if custom.name == option:
                return custom.crop_id
        return self.catalog.crops[0].crop_id

    # ------------------------------------------------------------------
    # Stage helpers
    # ------------------------------------------------------------------

    def stage_options(self, zone_id: str) -> list[str]:
        crop = self._resolve_crop(self.zone_states[zone_id].crop_id)
        return [self._stage_label(s) for s in crop.stages]

    def stage_current_option(self, zone_id: str) -> str:
        zone = self.zone_states[zone_id]
        crop = self._resolve_crop(zone.crop_id)
        return self._stage_label(resolve_stage_manual(crop, zone.manual_stage_id))

    def stage_option_to_id(self, zone_id: str, option: str) -> str:
        crop = self._resolve_crop(self.zone_states[zone_id].crop_id)
        for stage in crop.stages:
            if self._stage_label(stage) == option:
                return stage.stage_id
        return crop.stages[0].stage_id if crop.stages else "stage_1"

    # ------------------------------------------------------------------
    # Zone crop/stage setters
    # ------------------------------------------------------------------

    async def async_set_crop(self, zone_id: str, crop_id: str) -> None:
        crop = self._resolve_crop(crop_id)
        self.zone_states[zone_id] = replace(
            self.zone_states[zone_id],
            crop_id=crop_id,
            manual_stage_id=crop.stages[0].stage_id if crop.stages else "stage_1",
        )
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_set_stage_mode(self, zone_id: str, stage_mode: str) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], stage_mode=stage_mode)
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_set_manual_stage(self, zone_id: str, stage_id: str) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], manual_stage_id=stage_id)
        await self._async_save()
        await self._async_recompute_from_cache()

    # ------------------------------------------------------------------
    # Custom crop management
    # ------------------------------------------------------------------

    def custom_crop_options_for_stage(self) -> list[str]:
        """Options for the stage-form crop selector (custom crops only)."""
        if not self.custom_crops:
            return ["—"]
        return [c.name for c in self.custom_crops]

    def edit_crop_options(self) -> list[str]:
        if not self.custom_crops:
            return ["—"]
        return [c.name for c in self.custom_crops]

    def edit_stage_options(self) -> list[str]:
        crop = next((c for c in self.custom_crops if c.crop_id == self.forms.stage_edit_crop_id), None)
        if not crop or not crop.stages:
            return ["—"]
        return ["—"] + [s.label for s in crop.stages]

    async def async_set_edit_crop(self, crop_id: str) -> None:
        self.forms.stage_edit_crop_id = crop_id
        self.forms.stage_edit_stage_id = ""
        self.forms.stage_edit_name = ""
        self.forms.stage_edit_kc = 1.0
        self.forms.stage_edit_duration_open = 30
        self.forms.stage_edit_duration_gh = 25
        self._notify_entities()

    async def async_set_edit_stage(self, stage_id: str) -> None:
        self.forms.stage_edit_stage_id = stage_id
        self._populate_edit_form(self.forms.stage_edit_crop_id, stage_id)
        self._notify_entities()

    async def async_add_crop(self) -> None:
        """Create a new empty custom crop from the form name input."""
        from .dashboard import async_update_dashboard
        name = self.forms.crop_form_name.strip()
        if not name:
            return
        if any(c.name == name for c in self.custom_crops):
            return  # duplicate
        crop_id = f"custom_{''.join(c if c.isalnum() else '_' for c in name.lower())}"
        # Ensure unique crop_id
        existing_ids = {c.crop_id for c in self.custom_crops} | set(self.catalog.crop_map)
        base_id, n = crop_id, 2
        while crop_id in existing_ids:
            crop_id = f"{base_id}_{n}"
            n += 1
        new_crop = CustomCropDefinition(crop_id=crop_id, name=name, stages=[], root_depth_cm=self.forms.crop_form_root_depth)
        self.custom_crops.append(new_crop)
        self.forms.crop_form_name = ""
        await self._async_save()
        if self._crops_add_button_entities is not None:
            from .button import DeleteCropButton
            self._crops_add_button_entities([DeleteCropButton(self, crop_id)])
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_delete_crop(self, crop_id: str) -> None:
        """Delete a custom crop and reset any zones using it."""
        from .dashboard import async_update_dashboard
        from homeassistant.helpers import entity_registry as er
        crop = next((c for c in self.custom_crops if c.crop_id == crop_id), None)
        stage_ids = [s.stage_id for s in crop.stages] if crop else []
        self.custom_crops = [c for c in self.custom_crops if c.crop_id != crop_id]
        for zone_id, zone in self.zone_states.items():
            if zone.crop_id == crop_id:
                first = self.catalog.crops[0]
                self.zone_states[zone_id] = replace(
                    zone, crop_id=first.crop_id, manual_stage_id=first.stages[0].stage_id
                )
        ent_reg = er.async_get(self.hass)
        for uid in [
            f"{self.entry.entry_id}_crops_delete_{crop_id}",
            *(f"{self.entry.entry_id}_crops_delete_stage_{crop_id}_{sid}" for sid in stage_ids),
        ]:
            eid = ent_reg.async_get_entity_id("button", DOMAIN, uid)
            if eid:
                ent_reg.async_remove(eid)
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    # ------------------------------------------------------------------
    # Stage management
    # ------------------------------------------------------------------

    async def async_submit_stage_form(self) -> None:
        """Add a new stage or update an existing one depending on stage selection."""
        from .dashboard import async_update_dashboard
        crop_id = self.forms.stage_edit_crop_id
        if not crop_id and self.custom_crops:
            crop_id = self.custom_crops[0].crop_id
        if not crop_id:
            return
        crop = next((c for c in self.custom_crops if c.crop_id == crop_id), None)
        if not crop:
            return
        name = self.forms.stage_edit_name.strip()
        if not self.forms.stage_edit_stage_id:
            # --- ADD mode ---
            if not name:
                return
            existing_ids = {s.stage_id for s in crop.stages}
            n = len(crop.stages) + 1
            while f"stage_{n}" in existing_ids:
                n += 1
            stage_id = f"stage_{n}"
            crop.stages.append(CustomStageDefinition(
                stage_id=stage_id,
                label=name,
                kc=self.forms.stage_edit_kc,
                duration_days_open_field=self.forms.stage_edit_duration_open,
                duration_days_greenhouse=self.forms.stage_edit_duration_gh,
            ))
            self.forms.stage_edit_name = ""
            if self._crops_add_button_entities is not None:
                from .button import DeleteStageButton
                self._crops_add_button_entities([DeleteStageButton(self, crop.crop_id, stage_id)])
        else:
            # --- EDIT mode ---
            stage = next((s for s in crop.stages if s.stage_id == self.forms.stage_edit_stage_id), None)
            if not stage:
                return
            stage.label = name or stage.label
            stage.kc = self.forms.stage_edit_kc
            stage.duration_days_open_field = self.forms.stage_edit_duration_open
            stage.duration_days_greenhouse = self.forms.stage_edit_duration_gh
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_add_stage_to_crop(self) -> None:
        """Add a stage to the selected custom crop."""
        from .dashboard import async_update_dashboard
        crop_id = self.forms.stage_form_crop_id
        if not crop_id and self.custom_crops:
            crop_id = self.custom_crops[0].crop_id
        name = self.forms.stage_form_name.strip()
        if not crop_id or not name:
            return
        crop = next((c for c in self.custom_crops if c.crop_id == crop_id), None)
        if crop is None:
            return
        existing_ids = {s.stage_id for s in crop.stages}
        n = len(crop.stages) + 1
        while f"stage_{n}" in existing_ids:
            n += 1
        stage_id = f"stage_{n}"
        crop.stages.append(CustomStageDefinition(
            stage_id=stage_id,
            label=name,
            kc=self.forms.stage_form_kc,
            duration_days_open_field=self.forms.stage_form_duration_open,
            duration_days_greenhouse=self.forms.stage_form_duration_gh,
        ))
        self.forms.stage_form_name = ""
        if self._crops_add_button_entities is not None:
            from .button import DeleteStageButton
            self._crops_add_button_entities([DeleteStageButton(self, crop.crop_id, stage_id)])
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_delete_stage(self, crop_id: str, stage_id: str) -> None:
        from .dashboard import async_update_dashboard
        from homeassistant.helpers import entity_registry as er
        crop = next((c for c in self.custom_crops if c.crop_id == crop_id), None)
        if not crop:
            return
        crop.stages = [s for s in crop.stages if s.stage_id != stage_id]
        ent_reg = er.async_get(self.hass)
        unique_id = f"{self.entry.entry_id}_crops_delete_stage_{crop_id}_{stage_id}"
        entity_id = ent_reg.async_get_entity_id("button", DOMAIN, unique_id)
        if entity_id:
            ent_reg.async_remove(entity_id)
        if self.forms.stage_edit_crop_id == crop_id and self.forms.stage_edit_stage_id == stage_id:
            self.forms.stage_edit_stage_id = ""
            self.forms.stage_edit_name = ""
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_crop(self, crop_id: str):
        """Return CropDefinition for built-in or custom crop; fallback to first built-in."""
        if crop_id in self.catalog.crop_map:
            return self.catalog.crop_map[crop_id]
        for custom in self.custom_crops:
            if custom.crop_id == crop_id:
                return custom.to_crop_definition()
        return self.catalog.crops[0]

    def _crop_label(self, crop) -> str:
        return crop.label_en or _humanize_fallback(crop.crop_id) if self._is_english() else crop.label

    def _stage_label(self, stage) -> str:
        return stage.label_en or _humanize_fallback(stage.stage_id) if self._is_english() else stage.label

    def _populate_edit_form(self, crop_id: str, stage_id: str) -> None:
        crop = next((c for c in self.custom_crops if c.crop_id == crop_id), None)
        if not crop:
            return
        stage = next((s for s in crop.stages if s.stage_id == stage_id), None)
        if not stage:
            return
        self.forms.stage_edit_name = stage.label
        self.forms.stage_edit_kc = stage.kc
        self.forms.stage_edit_duration_open = stage.duration_days_open_field or 0
        self.forms.stage_edit_duration_gh = stage.duration_days_greenhouse or 0


def _humanize_fallback(value: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return text.replace("_", " ").strip().title()
