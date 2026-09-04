# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Select entities for IrriSynk."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, FREQUENCY_DAYS_OPTIONS, SOIL_TYPES, STAGE_MODES, ZONE_MODE_MIXED, ZONE_MODES, ZONE_MODES_ALL
from .entities.base import IrrigationCascadeEntity, IrrigationConfigEntity, IrrigationCropsEntity, IrrigationZoneEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SelectEntity] = [
        AllZonesModeSelect(coordinator),
        TelegramChatIdSelect(coordinator),
        CropForStageSelect(coordinator),
        EditStageCropSelect(coordinator),
        EditStageSelect(coordinator),
    ]
    for zone_id in coordinator.zone_states:
        entities.extend(
            [
                ZoneSwitchEntitySelect(coordinator, zone_id),
                IrrigationZoneModeSelect(coordinator, zone_id),
                IrrigationFrequencySelect(coordinator, zone_id),
                IrrigationCultivationModeSelect(coordinator, zone_id),
                IrrigationCropSelect(coordinator, zone_id),
                IrrigationStageModeSelect(coordinator, zone_id),
                IrrigationStageSelect(coordinator, zone_id),
                SoilTypeSelect(coordinator, zone_id),
            ]
        )
    for cascade in coordinator.cascades:
        entities.append(CascadeZoneSelectorSelect(coordinator, cascade.cascade_id))
    coordinator._cascades_add_select_entities = async_add_entities
    async_add_entities(entities)


class ZoneSwitchEntitySelect(IrrigationZoneEntity, SelectEntity):
    """Electrovalve switch entity selector for this zone."""

    _attr_translation_key = "switch_entity_id"
    _attr_icon = "mdi:electric-switch"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "switch_entity_id")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED,
                self._on_entity_registry_updated,
            )
        )

    @callback
    def _on_entity_registry_updated(self, event) -> None:
        self.async_write_ha_state()

    @property
    def options(self) -> list[str]:
        entity_reg = er.async_get(self.hass)
        entities = sorted(
            entry.entity_id
            for entry in entity_reg.entities.values()
            if entry.domain in ("switch", "valve")
        )
        current = self.coordinator.zone_states[self.zone_id].switch_entity_id
        if current and current not in entities:
            entities = [current] + entities
        return entities

    @property
    def current_option(self) -> str | None:
        return self.coordinator.zone_states[self.zone_id].switch_entity_id or None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_switch_entity(self.zone_id, option or None)


class IrrigationZoneModeSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "zone_mode"
    _attr_icon = "mdi:cog-outline"
    _attr_options = ZONE_MODES

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "zone_mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.zone_states[self.zone_id].zone_mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_zone_mode(self.zone_id, option)


class IrrigationFrequencySelect(IrrigationZoneEntity, SelectEntity):
    """Irrigation interval for scheduled/auto modes: every day, every N days."""

    _attr_translation_key = "frequency_days"
    _attr_icon = "mdi:calendar-sync-outline"
    _attr_options = FREQUENCY_DAYS_OPTIONS

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "frequency_days")

    @property
    def current_option(self) -> str:
        return str(self.coordinator.zone_states[self.zone_id].frequency_days)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_frequency_days(self.zone_id, int(option))


class AllZonesModeSelect(IrrigationConfigEntity, SelectEntity):
    _attr_translation_key = "all_zone_mode"
    _attr_icon = "mdi:cog-outline"
    _attr_options = ZONE_MODES_ALL

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "all_zone_mode")

    @property
    def current_option(self) -> str:
        if not self.coordinator.zone_states:
            return ZONE_MODE_MIXED
        modes = {zone.zone_mode for zone in self.coordinator.zone_states.values()}
        return next(iter(modes)) if len(modes) == 1 else ZONE_MODE_MIXED

    async def async_select_option(self, option: str) -> None:
        if option == ZONE_MODE_MIXED:
            return
        await self.coordinator.async_set_all_zones_mode(option)


class IrrigationCropSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "crop"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "crop")

    @property
    def options(self) -> list[str]:
        return self.coordinator.crop_options()

    @property
    def current_option(self) -> str:
        return self.coordinator.crop_current_option(self.zone_id)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_crop(self.zone_id, self.coordinator.crop_option_to_id(option))


class IrrigationStageModeSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "stage_mode"
    _attr_icon = "mdi:timeline-outline"
    _attr_options = STAGE_MODES

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "stage_mode")

    @property
    def current_option(self) -> str:
        return self.coordinator.zone_states[self.zone_id].stage_mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_stage_mode(self.zone_id, option)


class SoilTypeSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "soil_type"
    _attr_options = SOIL_TYPES
    _attr_icon = "mdi:layers-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "soil_type")

    @property
    def current_option(self) -> str:
        return self.coordinator.zone_states[self.zone_id].soil_type

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_soil_type(self.zone_id, option)


class IrrigationCultivationModeSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "cultivation_mode"
    _attr_icon = "mdi:layers-triple-outline"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "cultivation_mode")

    @property
    def options(self) -> list[str]:
        return self.coordinator.cultivation_mode_options()

    @property
    def current_option(self) -> str:
        return self.coordinator.zone_states[self.zone_id].cultivation_mode

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_cultivation_mode(self.zone_id, option)


class IrrigationStageSelect(IrrigationZoneEntity, SelectEntity):
    _attr_translation_key = "stage"
    _attr_icon = "mdi:compost"

    def __init__(self, coordinator, zone_id: str) -> None:
        super().__init__(coordinator, zone_id, "stage")

    @property
    def options(self) -> list[str]:
        return self.coordinator.stage_options(self.zone_id)

    @property
    def current_option(self) -> str:
        return self.coordinator.stage_current_option(self.zone_id)

    async def async_select_option(self, option: str) -> None:
        stage_id = self.coordinator.stage_option_to_id(self.zone_id, option)
        await self.coordinator.async_set_manual_stage(self.zone_id, stage_id)


class CropForStageSelect(IrrigationCropsEntity, SelectEntity):
    """Selects which custom crop to add a stage to."""

    _attr_translation_key = "crop_for_stage"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "form_stage_crop")

    @property
    def options(self) -> list[str]:
        return self.coordinator.custom_crop_options_for_stage()

    @property
    def current_option(self) -> str | None:
        opts = self.options
        if self.coordinator.forms.stage_form_crop_id:
            for crop in self.coordinator.custom_crops:
                if crop.crop_id == self.coordinator.forms.stage_form_crop_id:
                    return crop.name
        if self.coordinator.custom_crops:
            self.coordinator.forms.stage_form_crop_id = self.coordinator.custom_crops[0].crop_id
            return self.coordinator.custom_crops[0].name
        return opts[0] if opts else None

    async def async_select_option(self, option: str) -> None:
        crop = next((c for c in self.coordinator.custom_crops if c.name == option), None)
        self.coordinator.forms.stage_form_crop_id = crop.crop_id if crop else ""
        self.async_write_ha_state()


class EditStageCropSelect(IrrigationCropsEntity, SelectEntity):
    """Selects which custom crop to edit a stage in."""

    _attr_translation_key = "edit_stage_crop"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_crop")

    @property
    def options(self) -> list[str]:
        return self.coordinator.edit_crop_options()

    @property
    def current_option(self) -> str | None:
        if self.coordinator.forms.stage_edit_crop_id:
            for crop in self.coordinator.custom_crops:
                if crop.crop_id == self.coordinator.forms.stage_edit_crop_id:
                    return crop.name
        if self.coordinator.custom_crops:
            crop = self.coordinator.custom_crops[0]
            self.coordinator.forms.stage_edit_crop_id = crop.crop_id
            if crop.stages and not self.coordinator.forms.stage_edit_stage_id:
                self.coordinator.forms.stage_edit_stage_id = crop.stages[0].stage_id
                self.coordinator._populate_edit_form(crop.crop_id, crop.stages[0].stage_id)
            return crop.name
        opts = self.options
        return opts[0] if opts else None

    async def async_select_option(self, option: str) -> None:
        crop = next((c for c in self.coordinator.custom_crops if c.name == option), None)
        if crop:
            await self.coordinator.async_set_edit_crop(crop.crop_id)
        else:
            self.coordinator.forms.stage_edit_crop_id = ""
            self.async_write_ha_state()


class EditStageSelect(IrrigationCropsEntity, SelectEntity):
    """Selects which stage to edit within the selected crop."""

    _attr_translation_key = "edit_stage_stage"
    _attr_icon = "mdi:compost"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "edit_stage_stage")

    @property
    def options(self) -> list[str]:
        return self.coordinator.edit_stage_options()

    @property
    def current_option(self) -> str | None:
        if self.coordinator.forms.stage_edit_stage_id:
            crop = next((c for c in self.coordinator.custom_crops if c.crop_id == self.coordinator.forms.stage_edit_crop_id), None)
            if crop:
                stage = next((s for s in crop.stages if s.stage_id == self.coordinator.forms.stage_edit_stage_id), None)
                if stage:
                    return stage.label
        return "—"

    async def async_select_option(self, option: str) -> None:
        if option == "—":
            self.coordinator.forms.stage_edit_stage_id = ""
            self.coordinator.forms.stage_edit_name = ""
            self.coordinator.forms.stage_edit_kc = 1.0
            self.coordinator.forms.stage_edit_duration_open = 30
            self.coordinator.forms.stage_edit_duration_gh = 25
            self.async_write_ha_state()
            return
        crop = next((c for c in self.coordinator.custom_crops if c.crop_id == self.coordinator.forms.stage_edit_crop_id), None)
        if crop:
            stage = next((s for s in crop.stages if s.label == option), None)
            if stage:
                await self.coordinator.async_set_edit_stage(stage.stage_id)
                return
        self.async_write_ha_state()


class TelegramChatIdSelect(IrrigationConfigEntity, SelectEntity):
    """Select a Telegram notification target from available notify services and telegram_bot entities."""

    _attr_translation_key = "telegram_chat_id"
    _attr_icon = "mdi:chat"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "telegram_chat_id")

    def _telegram_targets(self) -> list[str]:
        targets: list[str] = []
        # Notify services containing "telegram"
        notify_svcs = self.hass.services.async_services().get("notify", {})
        for svc in sorted(notify_svcs):
            if "telegram" in svc.lower():
                targets.append(f"notify.{svc}")
        # Entities from the telegram_bot platform in the entity registry
        ent_reg = er.async_get(self.hass)
        for entry in ent_reg.entities.values():
            if entry.platform == "telegram_bot" and entry.entity_id not in targets:
                targets.append(entry.entity_id)
        return targets

    @property
    def options(self) -> list[str]:
        targets = self._telegram_targets()
        current = self.coordinator.telegram_chat_id
        if current and current not in targets:
            targets.insert(0, current)
        return targets or [""]

    @property
    def current_option(self) -> str | None:
        current = self.coordinator.telegram_chat_id
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_telegram_chat_id(option)
        self.async_write_ha_state()


class CascadeZoneSelectorSelect(IrrigationCascadeEntity, SelectEntity):
    """Dropdown listing zones not yet assigned to any cascade (for add-zone form)."""

    _attr_translation_key = "cascade_zone_selector"
    _attr_icon = "mdi:water-plus-outline"

    def __init__(self, coordinator, cascade_id: str) -> None:
        super().__init__(coordinator, cascade_id, "zone_selector")

    def _available_zone_ids(self) -> list[str]:
        already_assigned = {z for c in self.coordinator.cascades for z in c.zone_ids}
        return [z for z in self.coordinator.zone_states if z not in already_assigned]

    def _display_name(self, zone_id: str) -> str:
        return self.coordinator._zone_display_name(zone_id) or zone_id

    @property
    def options(self) -> list[str]:
        zones = self._available_zone_ids()
        return [self._display_name(z) for z in zones] or ["—"]

    @property
    def current_option(self) -> str | None:
        zones = self._available_zone_ids()
        if not zones:
            return None
        selected_id = self.coordinator._cascade_selector_state.get(self.cascade_id)
        if selected_id not in zones:
            selected_id = zones[0]
            self.coordinator._cascade_selector_state[self.cascade_id] = selected_id
        return self._display_name(selected_id)

    async def async_select_option(self, option: str) -> None:
        zones = self._available_zone_ids()
        zone_id = next((z for z in zones if self._display_name(z) == option), None)
        if zone_id:
            self.coordinator._cascade_selector_state[self.cascade_id] = zone_id
        self.async_write_ha_state()
