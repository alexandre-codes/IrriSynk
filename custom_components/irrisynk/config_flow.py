# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Config flow for IrriSynk."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_CLOUD_SENSOR,
    CONF_DASHBOARD_LANGUAGE,
    CONF_KC_CATALOG_PATH,
    CONF_LATITUDE,
    CONF_PRESSURE_SENSOR,
    CONF_RAIN_FORECAST_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_RAIN_SENSOR_MODE,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_WEATHER_ENTITY_ID,
    CONF_WIND_SENSOR,
    CONF_ZONES,
    DASHBOARD_LANGUAGE_AUTO,
    DASHBOARD_LANGUAGE_EN,
    DASHBOARD_LANGUAGE_FR,
    DEFAULT_KC_CATALOG_PATH,
    DEFAULT_NAME,
    DEFAULT_ZONE_IDS,
    DOMAIN,
    RAIN_SENSOR_MODE_CUMULATIVE,
    RAIN_SENSOR_MODE_INCREMENTAL,
)


async def _notify_restart(hass) -> None:
    try:
        from homeassistant.components.persistent_notification import async_create as pn_create  # type: ignore[import]
        lang = getattr(hass.config, "language", "en")
        if lang[:2] == "fr":
            msg = "IrriSynk est installé.\n\n**Redémarrez Home Assistant** pour activer le dashboard."
            title = "IrriSynk – Redémarrage requis"
        else:
            msg = "IrriSynk is installed.\n\n**Restart Home Assistant** to activate the dashboard."
            title = "IrriSynk – Restart required"
        result = pn_create(hass, msg, title=title, notification_id=f"{DOMAIN}_restart_required")
        if hasattr(result, "__await__"):
            await result
    except Exception:  # noqa: BLE001
        pass


_NAV_LABELS: dict[str, list[str]] = {
    "fr": ["Zones", "Météo", "Capteurs", "Électrovannes"],
    "en": ["Zones", "Weather", "Sensors", "Electrovalves"],
}


def _nav(hass, current: int) -> dict[str, str]:
    lang = getattr(hass.config, "language", "en")
    steps = _NAV_LABELS.get(lang[:2], _NAV_LABELS["en"])
    parts = [f"**{s}**" if i == current else s for i, s in enumerate(steps)]
    return {"nav": " › ".join(parts)}


_SENSOR_FIELDS = [
    CONF_WIND_SENSOR,
    CONF_TEMP_MAX_SENSOR,
    CONF_TEMP_MIN_SENSOR,
    CONF_PRESSURE_SENSOR,
    CONF_CLOUD_SENSOR,
    CONF_RAIN_SENSOR,
    CONF_RAIN_FORECAST_SENSOR,
]


def _options_or_data(entry, key, default=""):
    return entry.options.get(key, entry.data.get(key, default))


class IrriSynkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for irrisynk."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_config_meteo()
        default_lat = round(float(self.hass.config.latitude), 4)
        return self.async_show_form(
            step_id="user",
            data_schema=_base_schema(default_lat),
            description_placeholders=_nav(self.hass, 0),
        )

    async def async_step_config_meteo(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_config_sensors()
        return self.async_show_form(
            step_id="config_meteo",
            data_schema=_base_meteo_schema(),
            description_placeholders=_nav(self.hass, 1),
        )

    async def async_step_config_sensors(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_config_valves()
        return self.async_show_form(
            step_id="config_sensors",
            data_schema=_base_sensors_schema(),
            description_placeholders=_nav(self.hass, 2),
        )

    async def async_step_config_valves(self, user_input: dict[str, Any] | None = None):
        count = int(self._data.get("zone_count", 1))
        zones = [f"zone_{i + 1}" for i in range(count)]
        if user_input is not None:
            self._data.update(user_input)
            await _notify_restart(self.hass)
            return self.async_create_entry(
                title=self._data["name"],
                data=_build_data(self._data, zones),
            )
        return self.async_show_form(
            step_id="config_valves",
            data_schema=_config_valves_schema(zones),
            description_placeholders=_nav(self.hass, 3),
        )

    @staticmethod
    @config_entries.callback
    def async_get_options_flow(config_entry):
        return IrriSynkOptionsFlow()


class IrriSynkOptionsFlow(config_entries.OptionsFlow):
    """Manage integration options (multi-step wizard)."""

    def __init__(self) -> None:
        self._data: dict = {}

    async def async_step_init(self, user_input=None):
        return await self.async_step_zones(user_input)

    async def async_step_zones(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_meteo()
        current_lat = _options_or_data(
            self.config_entry,
            CONF_LATITUDE,
            round(float(self.hass.config.latitude), 4),
        ) or round(float(self.hass.config.latitude), 4)
        return self.async_show_form(
            step_id="zones",
            data_schema=_zones_schema(self.config_entry, float(current_lat)),
            description_placeholders=_nav(self.hass, 0),
        )

    async def async_step_meteo(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_sensors()
        return self.async_show_form(
            step_id="meteo",
            data_schema=_meteo_schema(self.config_entry),
            description_placeholders=_nav(self.hass, 1),
        )

    async def async_step_sensors(self, user_input=None):
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_valves()
        return self.async_show_form(
            step_id="sensors",
            data_schema=_sensors_schema(self.config_entry),
            description_placeholders=_nav(self.hass, 2),
        )

    async def async_step_valves(self, user_input=None):
        coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]
        if user_input is not None:
            for zone_id in coordinator.zone_states:
                await coordinator.async_set_switch_entity(
                    zone_id, user_input.get(f"valve_{zone_id}") or None
                )
            zones = [z.strip() for z in self._data[CONF_ZONES].split(",") if z.strip()]
            return self.async_create_entry(data=_build_data(self._data, zones))
        return self.async_show_form(
            step_id="valves",
            data_schema=_valves_schema(coordinator),
            description_placeholders=_nav(self.hass, 3),
        )


# ---------------------------------------------------------------------------
# Schema helpers — initial setup
# ---------------------------------------------------------------------------

def _base_schema(default_lat: float) -> vol.Schema:
    return vol.Schema({
        vol.Required("name", default=DEFAULT_NAME): str,
        vol.Required("zone_count", default=1): vol.All(int, vol.Range(min=1, max=200)),
        vol.Required(CONF_KC_CATALOG_PATH, default=DEFAULT_KC_CATALOG_PATH): str,
        vol.Required(CONF_LATITUDE, default=default_lat): vol.Coerce(float),
    })


_WEATHER_SELECTOR = EntitySelector(EntitySelectorConfig(domain="weather"))
_SENSOR_SELECTOR = EntitySelector(EntitySelectorConfig(domain="sensor"))
_VALVE_SELECTOR = EntitySelector(EntitySelectorConfig(domain=["switch", "valve"]))
_RAIN_MODE_SELECTOR = SelectSelector(SelectSelectorConfig(
    options=[RAIN_SENSOR_MODE_CUMULATIVE, RAIN_SENSOR_MODE_INCREMENTAL],
    translation_key="rain_sensor_mode",
    mode=SelectSelectorMode.DROPDOWN,
))


def _base_meteo_schema() -> vol.Schema:
    return vol.Schema({
        vol.Required(CONF_WEATHER_ENTITY_ID): _WEATHER_SELECTOR,
        vol.Optional(CONF_RAIN_FORECAST_SENSOR): _SENSOR_SELECTOR,
    })


def _base_sensors_schema() -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_RAIN_SENSOR): _SENSOR_SELECTOR,
        vol.Optional(CONF_RAIN_SENSOR_MODE, default=RAIN_SENSOR_MODE_CUMULATIVE): _RAIN_MODE_SELECTOR,
        vol.Optional(CONF_WIND_SENSOR): _SENSOR_SELECTOR,
        vol.Optional(CONF_TEMP_MAX_SENSOR): _SENSOR_SELECTOR,
        vol.Optional(CONF_TEMP_MIN_SENSOR): _SENSOR_SELECTOR,
        vol.Optional(CONF_PRESSURE_SENSOR): _SENSOR_SELECTOR,
        vol.Optional(CONF_CLOUD_SENSOR): _SENSOR_SELECTOR,
    })


# ---------------------------------------------------------------------------
# Schema helpers — options flow
# ---------------------------------------------------------------------------

_DASHBOARD_LANGUAGES = [DASHBOARD_LANGUAGE_AUTO, DASHBOARD_LANGUAGE_EN, DASHBOARD_LANGUAGE_FR]
_DASHBOARD_LANG_SELECTOR = SelectSelector(SelectSelectorConfig(
    options=_DASHBOARD_LANGUAGES,
    translation_key="dashboard_language",
    mode=SelectSelectorMode.DROPDOWN,
))


def _zones_schema(entry, current_lat: float) -> vol.Schema:
    def _cur(key, default=""):
        val = _options_or_data(entry, key, default)
        return val if val is not None else default

    zones_raw = _cur(CONF_ZONES, DEFAULT_ZONE_IDS)
    zones_default = (
        ", ".join(zones_raw) if isinstance(zones_raw, list)
        else (zones_raw or ", ".join(DEFAULT_ZONE_IDS))
    )

    return vol.Schema({
        vol.Required(CONF_ZONES, default=zones_default): str,
        vol.Required(CONF_LATITUDE, default=current_lat): vol.Coerce(float),
        vol.Required(CONF_KC_CATALOG_PATH, default=_cur(CONF_KC_CATALOG_PATH, DEFAULT_KC_CATALOG_PATH)): str,
        vol.Required(
            CONF_DASHBOARD_LANGUAGE,
            default=_cur(CONF_DASHBOARD_LANGUAGE, DASHBOARD_LANGUAGE_AUTO),
        ): _DASHBOARD_LANG_SELECTOR,
    })


def _eopt(key: str, value: str | None) -> vol.Optional:
    """Return vol.Optional with a default only when value is a non-empty string."""
    return vol.Optional(key, default=value) if value else vol.Optional(key)


def _meteo_schema(entry) -> vol.Schema:
    def _cur(key):
        return _options_or_data(entry, key) or None

    return vol.Schema({
        vol.Required(CONF_WEATHER_ENTITY_ID, default=_cur(CONF_WEATHER_ENTITY_ID)): _WEATHER_SELECTOR,
        _eopt(CONF_RAIN_FORECAST_SENSOR, _cur(CONF_RAIN_FORECAST_SENSOR)): _SENSOR_SELECTOR,
    })


def _sensors_schema(entry) -> vol.Schema:
    def _cur(key):
        return _options_or_data(entry, key) or None

    return vol.Schema({
        _eopt(CONF_RAIN_SENSOR, _cur(CONF_RAIN_SENSOR)): _SENSOR_SELECTOR,
        vol.Optional(CONF_RAIN_SENSOR_MODE, default=_options_or_data(entry, CONF_RAIN_SENSOR_MODE, RAIN_SENSOR_MODE_CUMULATIVE)): _RAIN_MODE_SELECTOR,
        _eopt(CONF_WIND_SENSOR, _cur(CONF_WIND_SENSOR)): _SENSOR_SELECTOR,
        _eopt(CONF_TEMP_MAX_SENSOR, _cur(CONF_TEMP_MAX_SENSOR)): _SENSOR_SELECTOR,
        _eopt(CONF_TEMP_MIN_SENSOR, _cur(CONF_TEMP_MIN_SENSOR)): _SENSOR_SELECTOR,
        _eopt(CONF_PRESSURE_SENSOR, _cur(CONF_PRESSURE_SENSOR)): _SENSOR_SELECTOR,
        _eopt(CONF_CLOUD_SENSOR, _cur(CONF_CLOUD_SENSOR)): _SENSOR_SELECTOR,
    })


def _config_valves_schema(zones: list[str]) -> vol.Schema:
    return vol.Schema({
        vol.Optional(f"valve_{zone_id}"): _VALVE_SELECTOR
        for zone_id in zones
    })


def _valves_schema(coordinator) -> vol.Schema:
    return vol.Schema({
        _eopt(f"valve_{zone_id}", coordinator.zone_states[zone_id].switch_entity_id): _VALVE_SELECTOR
        for zone_id in coordinator.zone_states
    })


# ---------------------------------------------------------------------------
# Shared builder
# ---------------------------------------------------------------------------

def _build_data(user_input: dict, zones: list[str]) -> dict:
    data = {
        CONF_WEATHER_ENTITY_ID: user_input[CONF_WEATHER_ENTITY_ID],
        CONF_ZONES: zones,
        CONF_KC_CATALOG_PATH: user_input[CONF_KC_CATALOG_PATH],
        CONF_LATITUDE: user_input[CONF_LATITUDE],
        CONF_RAIN_SENSOR_MODE: user_input.get(CONF_RAIN_SENSOR_MODE, RAIN_SENSOR_MODE_CUMULATIVE),
        CONF_DASHBOARD_LANGUAGE: user_input.get(CONF_DASHBOARD_LANGUAGE, DASHBOARD_LANGUAGE_AUTO),
    }
    for key in _SENSOR_FIELDS:
        val = user_input.get(key, "")
        if isinstance(val, str):
            val = val.strip()
        data[key] = val or None
    for zone_id in zones:
        key = f"valve_{zone_id}"
        if key in user_input:
            data[key] = user_input[key] or None
    return data
