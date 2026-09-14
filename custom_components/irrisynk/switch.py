# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Switch entities for IrriSynk."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IrrigationCoordinator
from .entities.base import IrrigationCascadeEntity, IrrigationCascadesEntity, IrrigationConfigEntity

try:
    from homeassistant.helpers import entity_registry as er
except ImportError:
    er = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities."""
    coordinator: IrrigationCoordinator = hass.data[DOMAIN][entry.entry_id]
    # Remove legacy global cascade switch (migration from single-cascade design)
    if er:
        ent_reg = er.async_get(hass)
        old_uid = f"{entry.entry_id}_config_cascade_switch"
        old_eid = ent_reg.async_get_entity_id("switch", DOMAIN, old_uid)
        if old_eid:
            ent_reg.async_remove(old_eid)
    entities: list[SwitchEntity] = [
        TelegramEnabledSwitch(coordinator),
        TelegramNotifyIrrigationsSwitch(coordinator),
        TelegramNotifyUnavailableSwitch(coordinator),
        CascadeAllEnabledSwitch(coordinator),
        GlobalPauseSwitch(coordinator),
        FrostProtectionSwitch(coordinator),
        NotifyHaEnabledSwitch(coordinator),
    ]
    for cascade in coordinator.cascades:
        entities.append(CascadeGroupSwitch(coordinator, cascade.cascade_id))
    coordinator._cascades_add_switch_entities = async_add_entities
    async_add_entities(entities)


class CascadeGroupSwitch(IrrigationCascadeEntity, SwitchEntity):
    """Switch enabling/disabling one cascade group."""

    _attr_translation_key = "cascade_enabled"
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator: IrrigationCoordinator, cascade_id: str) -> None:
        super().__init__(coordinator, cascade_id, "enabled")

    @property
    def is_on(self) -> bool:
        cascade = next((c for c in self.coordinator.cascades if c.cascade_id == self.cascade_id), None)
        return cascade.enabled if cascade else False

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_cascade_enabled(self.cascade_id, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_cascade_enabled(self.cascade_id, False)


class CascadeAllEnabledSwitch(IrrigationCascadesEntity, SwitchEntity):
    """Switch enabling/disabling all cascade groups at once."""

    _attr_translation_key = "cascade_all_enabled"
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "all_enabled")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.cascades) and all(c.enabled for c in self.coordinator.cascades)

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_all_cascades_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_all_cascades_enabled(False)


class GlobalPauseSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch suspending all automatic irrigation (zones and cascades) at once."""

    _attr_translation_key = "global_pause"
    _attr_icon = "mdi:pause-circle-outline"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "global_pause")

    @property
    def is_on(self) -> bool:
        return self.coordinator.global_pause_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_global_pause(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_global_pause(False)


class FrostProtectionSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch enabling automatic irrigation cancellation below the frost threshold."""

    _attr_translation_key = "frost_protection_enabled"
    _attr_icon = "mdi:snowflake-alert"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "frost_protection_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.frost_protection_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_frost_protection_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_frost_protection_enabled(False)


class NotifyHaEnabledSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch enabling alerts through a native Home Assistant notify service."""

    _attr_translation_key = "notify_ha_enabled"
    _attr_icon = "mdi:bell-ring-outline"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "notify_ha_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.notify_ha_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_notify_ha_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_notify_ha_enabled(False)


class TelegramEnabledSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch to enable/disable Telegram alert notifications."""

    _attr_translation_key = "telegram_enabled"
    _attr_icon = "mdi:send"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "telegram_enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.telegram_enabled

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_enabled(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_enabled(False)


class TelegramNotifyIrrigationsSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch to enable Telegram notifications for irrigation start/stop events."""

    _attr_translation_key = "telegram_notify_irrigations"
    _attr_icon = "mdi:water-check"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "telegram_notify_irrigations")

    @property
    def is_on(self) -> bool:
        return self.coordinator.telegram_notify_irrigations

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_notify_irrigations(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_notify_irrigations(False)


class TelegramNotifyUnavailableSwitch(IrrigationConfigEntity, SwitchEntity):
    """Switch to enable Telegram notifications when a valve is unavailable."""

    _attr_translation_key = "telegram_notify_unavailable"
    _attr_icon = "mdi:bell-alert"

    def __init__(self, coordinator: IrrigationCoordinator) -> None:
        super().__init__(coordinator, "telegram_notify_unavailable")

    @property
    def is_on(self) -> bool:
        return self.coordinator.telegram_notify_unavailable

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_notify_unavailable(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_telegram_notify_unavailable(False)
