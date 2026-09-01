# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""IrriSynk integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .const import DOMAIN, PLATFORMS
from .coordinator import IrrigationCoordinator
from .dashboard import async_update_dashboard
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

_JS_URL = f"/{DOMAIN}/irrisynk_zone_order_card.js"
_JS_FILE = Path(__file__).parent / "irrisynk_zone_order_card.js"
# v2: forces re-registration this session to migrate "module" → "js" resource type
_FRONTEND_KEY = f"{DOMAIN}_frontend_v2"


async def _async_register_frontend(hass: HomeAssistant) -> None:
    """Serve the JS card file and register it as a Lovelace resource (once per session)."""
    if hass.data.get(_FRONTEND_KEY):
        return
    hass.data[_FRONTEND_KEY] = True

    # Serve the static file
    try:
        from homeassistant.components.http import StaticPathConfig  # type: ignore[import]
        await hass.http.async_register_static_paths([
            StaticPathConfig(_JS_URL, str(_JS_FILE), cache_headers=False)
        ])
    except Exception:
        try:
            hass.http.register_static_path(_JS_URL, str(_JS_FILE), cache_headers=False)
        except Exception:
            _LOGGER.warning("IrriSynk: could not register static path for zone-order JS card")

    # 1. Frontend HTML injection — es5=True loads as a classic <script> (synchronous),
    #    not type="module" (deferred), so the custom element is defined before any render.
    try:
        from homeassistant.components.frontend import add_extra_js_url
        add_extra_js_url(hass, _JS_URL, es5=True)
    except Exception as exc:
        _LOGGER.warning("IrriSynk JS: add_extra_js_url failed: %s", exc)

    # 2. Live Lovelace resource collection — all clients (mobile app, mobile browser,
    #    desktop) fetch this via the lovelace/resources WebSocket API.
    await _async_ensure_lovelace_resource(hass, _JS_URL)


async def _async_ensure_lovelace_resource(hass: HomeAssistant, url: str) -> None:
    """Register url in the live Lovelace ResourceStorageCollection as a plain JS script."""
    lovelace_data = None
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA  # type: ignore[import]
        lovelace_data = hass.data.get(LOVELACE_DATA)
    except (ImportError, AttributeError):
        pass
    if lovelace_data is None:
        lovelace_data = hass.data.get("lovelace")

    resources = getattr(lovelace_data, "resources", None) if lovelace_data else None

    if resources is not None:
        try:
            existing: dict = getattr(resources, "data", {})

            js_registered = False
            for item_id, item in list(existing.items()):
                if item.get("url") != url:
                    continue
                if item.get("type") == "js":
                    js_registered = True
                else:
                    # Remove stale "module"-type entry — deferred loading causes
                    # "erreur de configuration" on mobile when the card renders first.
                    try:
                        await resources.async_delete_item(item_id)
                    except Exception as exc:
                        _LOGGER.debug("IrriSynk JS: could not remove old module resource: %s", exc)

            if not js_registered:
                await resources.async_create_item({"res_type": "js", "url": url})
                _LOGGER.info("IrriSynk: zone-order card JS registered as plain script")
            return
        except Exception as exc:
            _LOGGER.warning("IrriSynk JS: resource collection update failed: %s", exc)

    # Fallback: write directly to the storage file (effective after next HA restart)
    import uuid as _uuid
    from homeassistant.helpers.storage import Store
    store = Store(hass, 1, "lovelace_resources")
    raw = await store.async_load() or {}
    items: list[dict] = [i for i in raw.get("items", []) if i.get("url") != url]
    items.append({"id": str(_uuid.uuid4()), "type": "js", "url": url})
    await store.async_save({**raw, "items": items})
    _LOGGER.info("IrriSynk: zone-order card JS written to lovelace_resources storage")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up irrisynk from a config entry."""
    await _async_register_frontend(hass)

    coordinator = IrrigationCoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Remove devices/entities for zones that are no longer in the config
    _remove_orphaned_zone_devices(hass, entry, set(coordinator.zone_states))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)

    @callback
    def _on_ha_started(_event: Event | None = None) -> None:
        """Run dashboard update after HA is fully started so Lovelace is ready."""
        hass.async_create_task(async_update_dashboard(hass))

    if hass.is_running:
        # Integration reloaded while HA is already running
        _on_ha_started()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

    @callback
    def _on_device_renamed(event: Event) -> None:
        if event.data.get("action") != "update":
            return
        if "name_by_user" not in event.data.get("changes", {}):
            return
        device = dr.async_get(hass).async_get(event.data["device_id"])
        if device and entry.entry_id in device.config_entries:
            hass.async_create_task(async_update_dashboard(hass))

    @callback
    def _on_language_changed(_event: Event) -> None:
        hass.async_create_task(async_update_dashboard(hass))

    entry.async_on_unload(
        hass.bus.async_listen(dr.EVENT_DEVICE_REGISTRY_UPDATED, _on_device_renamed)
    )
    entry.async_on_unload(
        hass.bus.async_listen("core_config_updated", _on_language_changed)
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        coordinator.async_unload()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options are updated (e.g. zones added or renamed)."""
    await hass.config_entries.async_reload(entry.entry_id)


def _remove_orphaned_zone_devices(
    hass: HomeAssistant, entry: ConfigEntry, active_zone_ids: set[str]
) -> None:
    """Remove devices and entities for zones no longer present in the config."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)

    for device in dr.async_entries_for_config_entry(dev_reg, entry.entry_id):
        for domain, identifier in device.identifiers:
            if domain != DOMAIN:
                continue
            if identifier == entry.entry_id:
                # Global ETP device — keep it
                break
            # Non-zone suffixes (e.g. "config") — keep them
            suffix = identifier[len(entry.entry_id) + 1:]
            if suffix in ("config", "calculator", "cult_modes", "crops"):
                break
            # Zone device: identifier is "{entry_id}_{zone_id}"
            zone_id = suffix
            if zone_id not in active_zone_ids:
                for entity in er.async_entries_for_device(ent_reg, device.id):
                    ent_reg.async_remove(entity.entity_id)
                dev_reg.async_remove_device(device.id)
            break
