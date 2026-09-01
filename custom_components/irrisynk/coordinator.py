# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Data coordinator for IrriSynk."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from homeassistant.components.weather import ATTR_FORECAST_PRECIPITATION
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

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
    ZONE_MODE_AUTO,
    ZONE_MODE_MANUAL,
    ZONE_MODE_SCHEDULED,
    CONF_TEMP_MIN_SENSOR,
    CONF_WEATHER_ENTITY_ID,
    CONF_WIND_SENSOR,
    CONF_ZONES,
    CULTIVATION_MODE_OPEN_FIELD,
    CULTIVATION_MODES_GREENHOUSE,
    DASHBOARD_LANGUAGE_EN,
    DASHBOARD_LANGUAGE_FR,
    DEFAULT_ET0_CORRECTION_OPEN_FIELD,
    DOMAIN,
    RAW_FRACTION,
    RAIN_SENSOR_MODE_INCREMENTAL,
    SOIL_AWC_MM_PER_M,
    SOIL_DEFAULT,
    SOIL_INITIAL_ROOT_DEPTH_CM,
    STAGE_MODE_AUTO_BY_DAYS,
    STAGE_MODE_MANUAL,
    UPDATE_INTERVAL,
)
from .coordinator_cascade import CascadeMixin
from .coordinator_crops import CropsMixin
from .coordinator_scheduling import SchedulingMixin
from .forms import FormState
from .models.domain import (
    CustomCropDefinition,
    CustomCultivationMode,
    KcCatalog,
    ZoneComputedState,
    ZoneState,
)
from .models.irrigation_math import compute_et0_fao56, compute_water_need_mm, mm_to_minutes
from .models.kc_catalog import load_catalog_from_path
from .models.stage_engine import _stage_duration, resolve_stage_auto, resolve_stage_index, resolve_stage_manual
from .store import IrrigationStore

_LOGGER = logging.getLogger(__name__)
_DEFAULT_ET0 = 3.5


def _compute_irrigation_from_states(states: list, flow_mm_h: float, end: datetime) -> float:
    """Compute irrigation (mm) from switch/valve state history."""
    try:
        on_seconds = 0.0
        for i, state in enumerate(states):
            if state.state in ("on", "open"):
                next_time = states[i + 1].last_changed if i + 1 < len(states) else end
                on_seconds += (next_time - state.last_changed).total_seconds()
        return round(on_seconds / 3600.0 * flow_mm_h, 2)
    except Exception:
        return 0.0


class IrrigationCoordinator(SchedulingMixin, CascadeMixin, CropsMixin, DataUpdateCoordinator[dict[str, ZoneComputedState]]):
    """Coordinator managing all zone calculations and irrigation scheduling."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name="IrriSynk", update_interval=UPDATE_INTERVAL)
        self.entry = entry
        self.store = IrrigationStore(hass)
        self.catalog: KcCatalog | None = None  # loaded asynchronously in async_initialize
        self.zone_states: dict[str, ZoneState] = {}
        self.et0_mm: float = _DEFAULT_ET0
        self.rain_mm_today: float = 0.0  # saved for J-1 balance at midnight
        self._schedule_unsub = None
        self._switch_unsubs: list = []  # unsubscribe callbacks for switch state listeners
        self._active_irrigations: set[str] = set()
        self._pending_start: dict[str, int] = {}  # zone_id → retries remaining
        self._zones_irrigation_reset: set[str] = set()  # force irrigation_today_mm=0 for one cycle
        # Cascade irrigation — multiple named groups
        self.cascades: list = []  # list[CascadeGroup] — loaded in async_config_entry_first_refresh
        self._cascade_active: dict[str, list[str]] = {}  # cascade_id → running zone sequence
        self._cascades_add_switch_entities = None
        self._cascades_add_time_entities = None
        self._cascades_add_button_entities = None
        self._cascades_add_select_entities = None
        self._cascade_selector_state: dict[str, str] = {}  # cascade_id → selected zone_id
        # Custom cultivation modes (persisted)
        self.custom_cultivation_modes: list[CustomCultivationMode] = []
        # Callback to dynamically add button entities (set by button platform setup)
        self._cult_modes_add_button_entities = None
        # Custom crops (persisted)
        self.custom_crops: list[CustomCropDefinition] = []
        # Callback for dynamic delete-crop button creation
        self._crops_add_button_entities = None
        # Telegram alerts (persisted)
        self.telegram_enabled: bool = False
        self.telegram_chat_id: str = ""
        self.telegram_notify_irrigations: bool = True
        self.telegram_notify_unavailable: bool = True
        # Transient form state (not persisted — reset to defaults on restart)
        self.forms: FormState = FormState()

    async def async_config_entry_first_refresh(self) -> None:
        """Load persisted state then register listeners."""
        loaded, cascades, custom_modes, custom_crops, telegram = await self.store.async_load()
        self.cascades = cascades
        self.custom_cultivation_modes = custom_modes
        self.custom_crops = custom_crops
        self.telegram_enabled = telegram.get("enabled", False)
        self.telegram_chat_id = telegram.get("chat_id", "")
        self.telegram_notify_irrigations = telegram.get("notify_irrigations", True)
        self.telegram_notify_unavailable = telegram.get("notify_unavailable", True)
        zones = self.entry.options.get(CONF_ZONES, self.entry.data[CONF_ZONES])
        active = set(zones)
        if loaded:
            removed = set(loaded.keys()) - active
            self.zone_states = {zid: s for zid, s in loaded.items() if zid in active}
            if removed:
                _LOGGER.info(f"Purging removed zones from store: {removed}")
                await self._async_save()
        for zone_id in zones:
            if zone_id not in self.zone_states:
                first_crop = self.catalog.crops[0]
                valve_key = f"valve_{zone_id}"
                switch_entity_id = (
                    self.entry.options.get(valve_key)
                    or self.entry.data.get(valve_key)
                )
                self.zone_states[zone_id] = ZoneState(
                    zone_id=zone_id,
                    crop_id=first_crop.crop_id,
                    stage_mode=STAGE_MODE_MANUAL,
                    cultivation_mode=CULTIVATION_MODE_OPEN_FIELD,
                    manual_stage_id=first_crop.stages[0].stage_id,
                    et0_correction_factor=DEFAULT_ET0_CORRECTION_OPEN_FIELD,
                    switch_entity_id=switch_entity_id or None,
                )
        await super().async_config_entry_first_refresh()
        await self._async_recover_irrigation_state()
        self._register_listeners()

    def async_unload(self) -> None:
        """Cancel background listeners."""
        if self._schedule_unsub:
            self._schedule_unsub()
            self._schedule_unsub = None
        for unsub in self._switch_unsubs:
            unsub()
        self._switch_unsubs.clear()

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def _register_listeners(self) -> None:
        if self._schedule_unsub:
            self._schedule_unsub()
        for unsub in self._switch_unsubs:
            unsub()
        self._switch_unsubs.clear()

        @callback
        def _on_tick(now: datetime) -> None:
            self.hass.async_create_task(self._async_dispatch(now))

        # Fires every minute (second=0); also catches 00:00 for midnight balance
        self._schedule_unsub = async_track_time_change(self.hass, _on_tick, second=0)

        # Re-run full update once HA is fully started so weather entities are available
        if not self.hass.is_running:
            @callback
            def _on_ha_started(_) -> None:
                self.hass.async_create_task(self.async_request_refresh())
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_ha_started)

        # Watch all configured switches for unexpected state changes
        switch_ids = list({
            zone.switch_entity_id
            for zone in self.zone_states.values()
            if zone.switch_entity_id
        })
        if switch_ids:
            @callback
            def _on_switch_change(event) -> None:
                self.hass.async_create_task(self._async_on_switch_state_change(event))

            self._switch_unsubs.append(
                async_track_state_change_event(self.hass, switch_ids, _on_switch_change)
            )

    # ------------------------------------------------------------------
    # Midnight J-1 balance
    # ------------------------------------------------------------------

    async def _async_midnight_balance_update(self, now: datetime) -> None:
        """Compute J-1 actual water balance per zone and persist it."""
        yesterday_start = dt_util.start_of_local_day(now - timedelta(days=1))
        yesterday_end = dt_util.start_of_local_day(now)

        # ET0 J-1: use sensor history if available, otherwise saved forecast ET0
        et0_j1 = await self._async_compute_et0_j1(yesterday_start, yesterday_end)
        # Rain J-1: sensor or saved forecast rain
        rain_j1 = await self._async_compute_rain_j1(yesterday_start, yesterday_end)

        last_data = self.data or {}
        for zone_id, zone in self.zone_states.items():
            kc = getattr(last_data.get(zone_id), "kc_current", 1.0)
            et0_zone_j1 = round(et0_j1 * zone.et0_correction_factor, 2)
            actual_demand = et0_zone_j1 * kc

            irrigation_j1 = 0.0
            if zone.switch_entity_id:
                irrigation_j1 = await self._async_compute_irrigation_j1(
                    zone.switch_entity_id, zone.flow_mm_h, yesterday_start, yesterday_end
                )

            effective_rain_j1 = (
                0.0
                if zone.cultivation_mode in CULTIVATION_MODES_GREENHOUSE
                else round(rain_j1 * zone.rain_effectiveness_pct / 100.0, 2)
            )
            actual_supply = effective_rain_j1 + irrigation_j1
            daily_delta = round(actual_supply - actual_demand, 2)
            # Cumulative SWD: caps derived from RAW = 0.4 × TAW (soil_type × progressive root depth).
            # Both surplus (+RAW) and deficit (-RAW) are bounded by the soil's readily available water.
            raw = self._compute_raw_mm(zone_id)
            new_balance = zone.soil_water_balance_mm + daily_delta
            balance = round(max(-raw, min(+raw, new_balance)), 2)

            _LOGGER.info(
                f"Zone {zone_id} J-1: ET0={et0_zone_j1:.2f} Kc={kc:.2f} demand={actual_demand:.2f} "
                f"rain={effective_rain_j1:.2f} irr={irrigation_j1:.2f} "
                f"delta={daily_delta:+.2f} → balance={balance:+.2f} mm (RAW cap ±{raw} mm)"
            )
            self.zone_states[zone_id] = replace(zone, soil_water_balance_mm=balance)

        await self._async_save()
        await self.async_request_refresh()

    async def _async_compute_et0_j1(self, start: datetime, end: datetime) -> float:
        """Compute ET0 for J-1 from sensor history if configured, else use saved forecast ET0."""
        wind_id = self._cfg_sensor(CONF_WIND_SENSOR)
        tmax_id = self._cfg_sensor(CONF_TEMP_MAX_SENSOR)
        tmin_id = self._cfg_sensor(CONF_TEMP_MIN_SENSOR)
        pressure_id = self._cfg_sensor(CONF_PRESSURE_SENSOR)
        cloud_id = self._cfg_sensor(CONF_CLOUD_SENSOR)

        has_sensors = any((wind_id, tmax_id, tmin_id, pressure_id, cloud_id))
        if not has_sensors:
            # Fall back to the forecast-based ET0 we computed yesterday
            return self.et0_mm

        try:
            stats = await self._async_sensor_day_stats(
                {
                    "wind": wind_id,
                    "tmax": tmax_id,
                    "tmin": tmin_id,
                    "pressure": pressure_id,
                    "cloud": cloud_id,
                },
                start,
                end,
            )

            # tmax: use sensor max if dedicated sensor, else max of temp sensor
            tmax = stats["tmax_max"] if "tmax_max" in stats else (stats["tmin_max"] if "tmin_max" in stats else 25.0)
            tmin = stats["tmin_min"] if "tmin_min" in stats else (stats["tmax_min"] if "tmax_min" in stats else tmax - 12.0)
            wind_kmh = stats["wind_avg"] if "wind_avg" in stats else 7.2
            pressure_hpa = stats["pressure_avg"] if "pressure_avg" in stats else 1013.0
            cloud_pct = stats["cloud_avg"] if "cloud_avg" in stats else 40.0

            doy = start.timetuple().tm_yday
            return compute_et0_fao56(
                tmax_c=tmax,
                tmin_c=tmin,
                wind_kmh=wind_kmh,
                pressure_hpa=pressure_hpa,
                cloud_cover_pct=cloud_pct,
                latitude_deg=self._get_latitude(),
                doy=doy,
            )
        except Exception as exc:
            _LOGGER.warning(f"Could not compute ET0 from sensors ({exc}), using forecast ET0")
            return self.et0_mm

    async def _async_compute_rain_j1(self, start: datetime, end: datetime) -> float:
        """Return actual rain for J-1: local rain sensor if configured, else weather forecast."""
        rain_id = self._cfg_sensor(CONF_RAIN_SENSOR)

        if rain_id:
            mode = self._cfg(CONF_RAIN_SENSOR_MODE, "cumulative")
            try:
                states = await self._async_get_states_range(rain_id, start, end)
                if not states:
                    return self.rain_mm_today

                if mode == RAIN_SENSOR_MODE_INCREMENTAL:
                    baseline = _safe_float(states[0].state) or 0.0
                    last = _safe_float(states[-1].state) or 0.0
                    return max(0.0, last - baseline)
                else:
                    return _safe_float(states[-1].state) or 0.0
            except Exception as exc:
                _LOGGER.warning(f"Could not read rain sensor history ({exc})")

        return self.rain_mm_today

    async def _async_compute_irrigation_j1(
        self, entity_id: str, flow_mm_h: float, start: datetime, end: datetime
    ) -> float:
        """Return actual irrigation (mm) for zone on J-1 from switch/valve history."""
        try:
            states = await self._async_get_states_range(entity_id, start, end)
            return _compute_irrigation_from_states(states, flow_mm_h, end)
        except Exception as exc:
            _LOGGER.warning(f"Could not read switch history for {entity_id} ({exc})")
            return 0.0

    # ------------------------------------------------------------------
    # Recorder helpers
    # ------------------------------------------------------------------

    async def _async_get_states_batch(self, entity_ids: list[str], start: datetime, end: datetime) -> dict[str, list]:
        """Fetch significant state changes for multiple entities in a single Recorder query."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.history import get_significant_states

        instance = get_instance(self.hass)
        return await instance.async_add_executor_job(
            get_significant_states, self.hass, start, end, entity_ids
        )

    async def _async_get_states_range(self, entity_id: str, start: datetime, end: datetime) -> list:
        """Fetch significant state changes for a single entity."""
        history = await self._async_get_states_batch([entity_id], start, end)
        return history.get(entity_id, [])

    async def _async_sensor_day_stats(
        self, sensors: dict[str, str | None], start: datetime, end: datetime
    ) -> dict[str, float]:
        """Return min/max/avg for each configured sensor over a day — single batch query."""
        entity_ids = [eid for eid in sensors.values() if eid]
        if not entity_ids:
            return {}
        all_states = await self._async_get_states_batch(entity_ids, start, end)
        result: dict[str, float] = {}
        for key, entity_id in sensors.items():
            if not entity_id:
                continue
            values = [v for s in all_states.get(entity_id, []) if (v := _safe_float(s.state)) is not None]
            if not values:
                continue
            result[f"{key}_min"] = min(values)
            result[f"{key}_max"] = max(values)
            result[f"{key}_avg"] = sum(values) / len(values)
        return result

    # ------------------------------------------------------------------
    # Data update (today — pure forecast)
    # ------------------------------------------------------------------

    async def _async_get_weather_forecast(self, entity_id: str, attrs: dict) -> list[dict]:
        """Fetch daily forecast — uses the modern service API (HA 2024.3+) with
        a fallback to the legacy ``forecast`` attribute for older installs."""
        try:
            result = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "daily"},
                blocking=True,
                return_response=True,
            )
            if result and entity_id in result:
                forecast = result[entity_id].get("forecast", [])
                if forecast:
                    return forecast
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug(f"weather.get_forecasts failed ({exc}) — using legacy attribute")
        # Legacy fallback (deprecated since HA 2024.3)
        return attrs.get("forecast") or []

    async def _async_update_data(self) -> dict[str, ZoneComputedState]:
        weather_entity = self.entry.options.get(CONF_WEATHER_ENTITY_ID, self.entry.data[CONF_WEATHER_ENTITY_ID])
        state = self.hass.states.get(weather_entity)
        attrs = state.attributes if state else {}
        forecast = await self._async_get_weather_forecast(weather_entity, attrs) if state else []

        et0_mm = _DEFAULT_ET0
        rain_mm = 0.0
        if state:
            provided = attrs.get("et0_mm") or attrs.get("evapotranspiration")
            if provided is not None:
                et0_mm = float(provided)
            else:
                et0_mm = self._compute_et0_forecast(attrs, forecast)
            rain_mm = self._get_rain_mm(forecast)

        self.et0_mm = round(et0_mm, 2)
        self.rain_mm_today = round(rain_mm, 2)

        return await self._async_compute_zones(self.et0_mm, self.rain_mm_today)

    async def _async_compute_zones(self, et0_mm: float, rain_mm: float) -> dict[str, ZoneComputedState]:
        """Compute ZoneComputedState for all zones from provided ET₀ and rain (no weather fetch)."""
        now = dt_util.now()
        today = now.date()
        today_start = dt_util.start_of_local_day(now)

        # Single batch Recorder query for all switch/valve entities
        switch_ids = list({
            z.switch_entity_id
            for z in self.zone_states.values()
            if z.switch_entity_id
        })
        switch_histories: dict[str, list] = (
            await self._async_get_states_batch(switch_ids, today_start, now)
            if switch_ids else {}
        )

        data: dict[str, ZoneComputedState] = {}
        for zone_id, zone in self.zone_states.items():
            crop = self._resolve_crop(zone.crop_id)
            stage = (
                resolve_stage_auto(crop, zone.planting_date, today, zone.cultivation_mode)
                if zone.stage_mode == STAGE_MODE_AUTO_BY_DAYS
                else resolve_stage_manual(crop, zone.manual_stage_id)
            )
            et0_zone = round(et0_mm * zone.et0_correction_factor, 2)
            effective_rain = (
                0.0
                if zone.cultivation_mode in CULTIVATION_MODES_GREENHOUSE
                else round(rain_mm * (zone.rain_effectiveness_pct / 100.0), 2)
            )
            irrigation_today_mm = 0.0
            if zone.switch_entity_id and zone_id not in self._zones_irrigation_reset:
                states = switch_histories.get(zone.switch_entity_id, [])
                irrigation_today_mm = _compute_irrigation_from_states(states, zone.flow_mm_h, now)
            self._zones_irrigation_reset.discard(zone_id)
            balance_mm = zone.soil_water_balance_mm if zone.switch_entity_id else 0.0
            water_need = compute_water_need_mm(
                et0_zone, stage.kc, effective_rain + irrigation_today_mm,
                zone.soil_buffer_mm, balance_mm,
            )
            duration = min(mm_to_minutes(water_need, zone.flow_mm_h), zone.max_duration_min)

            confidence = 100
            notes: list[str] = []
            if zone.stage_mode == STAGE_MODE_AUTO_BY_DAYS and zone.planting_date is None:
                confidence = 70
                notes.append("Planting date missing in auto mode.")

            soil_capacity_mm = self._compute_raw_mm(zone_id)
            data[zone_id] = ZoneComputedState(
                current_stage_id=stage.stage_id,
                current_stage_label=self._stage_label(stage),
                kc_current=stage.kc,
                water_need_mm=water_need,
                recommended_duration_min=duration if zone.zone_mode != ZONE_MODE_MANUAL else 0.0,
                effective_duration_min=(
                    zone.scheduled_duration_min if zone.zone_mode == ZONE_MODE_SCHEDULED
                    else (duration if zone.zone_mode == ZONE_MODE_AUTO else 0.0)
                ),
                effective_rain_mm=effective_rain,
                confidence=confidence,
                soil_water_balance_mm=zone.soil_water_balance_mm,
                irrigation_today_mm=irrigation_today_mm,
                soil_capacity_mm=soil_capacity_mm,
                notes=notes,
            )
        return data

    async def _async_recompute_from_cache(self) -> None:
        """Recompute all zone data from cached ET₀ and rain — no weather API call."""
        data = await self._async_compute_zones(self.et0_mm, self.rain_mm_today)
        self.async_set_updated_data(data)

    # ------------------------------------------------------------------
    # ETP from forecast (pure weather entity — no sensor override for today)
    # ------------------------------------------------------------------

    def _compute_et0_forecast(self, attrs: dict, forecast: list[dict]) -> float:
        """Compute today's ET0 from weather forecast only."""
        fc0 = forecast[0] if forecast else {}

        tmax = _safe_float(fc0.get("temperature")) or _safe_float(attrs.get("temperature")) or 25.0
        tmin = _safe_float(fc0.get("templow")) or (tmax - 12.0)
        wind_kmh = (
            _safe_float(fc0.get("wind_speed")) or _safe_float(attrs.get("wind_speed")) or 7.2
        )
        pressure_hpa = (
            _safe_float(fc0.get("pressure")) or _safe_float(attrs.get("pressure")) or 1013.0
        )
        cloud_cover_pct = (
            _safe_float(fc0.get("cloud_coverage")) or _safe_float(attrs.get("cloud_coverage")) or 40.0
        )
        doy = dt_util.now().timetuple().tm_yday

        return compute_et0_fao56(
            tmax_c=tmax, tmin_c=tmin, wind_kmh=wind_kmh,
            pressure_hpa=pressure_hpa, cloud_cover_pct=cloud_cover_pct,
            latitude_deg=self._get_latitude(), doy=doy,
        )

    def _get_rain_mm(self, forecast: list[dict]) -> float:
        """Return today's forecast rain.

        Priority:
        1. Dedicated rain forecast sensor (CONF_RAIN_FORECAST_SENSOR)
        2. weather.get_forecasts precipitation field
        3. 0.0
        """
        sensor_id = self._cfg_sensor(CONF_RAIN_FORECAST_SENSOR)
        if sensor_id:
            val = self._get_entity_float(sensor_id)
            if val is not None:
                        return val
        if forecast:
            return float(forecast[0].get(ATTR_FORECAST_PRECIPITATION, 0.0) or 0.0)
        return 0.0

    # ------------------------------------------------------------------
    # Catalog & zone helpers
    # ------------------------------------------------------------------

    async def async_initialize(self) -> None:
        """Load catalog from disk via executor (non-blocking)."""
        self.catalog = await self.hass.async_add_executor_job(self._load_catalog_sync)

    def _load_catalog_sync(self) -> KcCatalog:
        catalog_path = self.entry.options.get(CONF_KC_CATALOG_PATH, self.entry.data[CONF_KC_CATALOG_PATH])
        if not Path(catalog_path).is_absolute():
            catalog_path = Path(__file__).parent / catalog_path
        return load_catalog_from_path(Path(catalog_path))

    def _custom_crop_options(self) -> list[str]:
        return [c.name for c in self.custom_crops]

    async def async_reorder_zones(self, new_order: list[str]) -> None:
        """Reorder zone_states; cascade sequence and dashboard follow automatically."""
        from .dashboard import async_update_dashboard
        valid = [z for z in new_order if z in self.zone_states]
        tail = [z for z in self.zone_states if z not in valid]
        self.zone_states = {z: self.zone_states[z] for z in valid + tail}
        self._refresh_all_cascade_times()
        await self._async_save()
        self._notify_entities()
        await async_update_dashboard(self.hass)

    async def async_reset_soil_balance(self, zone_id: str) -> None:
        """Reset J-1 water balance to zero and persist (no refresh triggered)."""
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], soil_water_balance_mm=0.0)
        await self._async_save()

    async def async_set_soil_type(self, zone_id: str, soil_type: str) -> None:
        """Update soil type for a zone and recompute."""
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], soil_type=soil_type)
        await self._async_save()
        await self._async_recompute_from_cache()

    def _compute_raw_mm(self, zone_id: str) -> float:
        """Compute Readily Available Water (RAW = 0.4 × TAW) for the zone's current state.

        Uses progressive root depth: linear ramp from SOIL_INITIAL_ROOT_DEPTH_CM
        (at stage 0) to crop's max root_depth_cm (at last stage).
        """
        from datetime import date as _date
        zone = self.zone_states[zone_id]
        crop = self._resolve_crop(zone.crop_id)
        root_depth_max = getattr(crop, "root_depth_cm", None) or 50

        if zone.stage_mode == STAGE_MODE_AUTO_BY_DAYS:
            stage_idx = resolve_stage_index(
                crop, zone.planting_date, _date.today(), zone.cultivation_mode
            )
        else:
            stage_idx = next(
                (i for i, s in enumerate(crop.stages) if s.stage_id == zone.manual_stage_id),
                0,
            )

        durations = [_stage_duration(s, zone.cultivation_mode) or 0 for s in crop.stages]
        total_dur = sum(durations) or 1
        cum_dur = sum(durations[: stage_idx + 1])
        ratio = cum_dur / total_dur
        z_eff = SOIL_INITIAL_ROOT_DEPTH_CM + (root_depth_max - SOIL_INITIAL_ROOT_DEPTH_CM) * ratio
        awc = SOIL_AWC_MM_PER_M.get(zone.soil_type, SOIL_AWC_MM_PER_M[SOIL_DEFAULT])
        return round(RAW_FRACTION * awc * z_eff / 100.0, 1)

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    async def async_create_crop(self) -> None:
        """Create a new empty custom crop from the form name input."""
        await self.async_add_crop()

    async def async_delete_custom_crop(self, crop_id: str) -> None:
        """Delete a custom crop and reset any zones using it."""
        await self.async_delete_crop(crop_id)

    async def async_save_stage_edit(self) -> None:
        """Save edits to the currently selected stage."""
        await self.async_update_stage()

    async def async_set_zone_mode(self, zone_id: str, mode: str) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], zone_mode=mode)
        self._refresh_all_cascade_times()
        await self._async_save_and_notify(zone_id)

    async def async_set_all_zones_mode(self, mode: str) -> None:
        for zone_id in self.zone_states:
            self.zone_states[zone_id] = replace(self.zone_states[zone_id], zone_mode=mode)
        self._refresh_all_cascade_times()
        await self._async_save_and_notify(list(self.zone_states.keys()))

    async def async_set_all_zones_number(self, key: str, value: float) -> None:
        """Set a numeric field on every zone at once."""
        for zone_id in self.zone_states:
            self.zone_states[zone_id] = replace(self.zone_states[zone_id], **{key: value})
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_set_planting_date(self, zone_id: str, planting_date: date | None) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], planting_date=planting_date)
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_set_scheduled_duration(self, zone_id: str, value: float) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], scheduled_duration_min=value)
        await self._async_save_and_notify(zone_id)

    async def async_set_number(self, zone_id: str, key: str, value: float) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], **{key: value})
        await self._async_save()
        await self._async_recompute_from_cache()

    async def async_set_switch_entity(self, zone_id: str, entity_id: str | None) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], switch_entity_id=entity_id)
        self._register_listeners()  # re-subscribe with updated switch list
        await self._async_save_and_refresh()

    async def async_set_start_time(self, zone_id: str, time_str: str | None) -> None:
        self.zone_states[zone_id] = replace(self.zone_states[zone_id], start_time_str=time_str)
        await self._async_save()
        self._notify_entities()

    def _notify_entities(self) -> None:
        """Push current data to all listeners without re-fetching weather."""
        if self.data is not None:
            self.async_set_updated_data(self.data)

    async def _async_save_and_notify(self, zone_ids: list[str] | str) -> None:
        """Notify entities immediately then save to disk in background."""
        if not self.data:
            await self.async_request_refresh()
            return
        if isinstance(zone_ids, str):
            zone_ids = [zone_ids]
        data = dict(self.data)
        for zone_id in zone_ids:
            if zone_id not in data:
                continue
            zone = self.zone_states[zone_id]
            computed = data[zone_id]
            effective = (
                zone.scheduled_duration_min if zone.zone_mode == ZONE_MODE_SCHEDULED
                else (computed.recommended_duration_min if zone.zone_mode == ZONE_MODE_AUTO else 0.0)
            )
            data[zone_id] = replace(computed, effective_duration_min=effective)
        self.async_set_updated_data(data)
        self.hass.async_create_task(self._async_save())

    async def _async_save(self) -> None:
        """Persist zone states, cascade groups, custom cultivation modes, custom crops, and Telegram config."""
        await self.store.async_save(
            self.zone_states,
            cascades=self.cascades,
            custom_cultivation_modes=self.custom_cultivation_modes,
            custom_crops=self.custom_crops,
            telegram_enabled=self.telegram_enabled,
            telegram_chat_id=self.telegram_chat_id,
            telegram_notify_irrigations=self.telegram_notify_irrigations,
            telegram_notify_unavailable=self.telegram_notify_unavailable,
        )

    async def async_set_telegram_enabled(self, enabled: bool) -> None:
        self.telegram_enabled = enabled
        await self._async_save()
        self._notify_entities()

    async def async_set_telegram_chat_id(self, chat_id: str) -> None:
        self.telegram_chat_id = chat_id
        await self._async_save()

    async def async_set_telegram_notify_irrigations(self, enabled: bool) -> None:
        self.telegram_notify_irrigations = enabled
        await self._async_save()
        self._notify_entities()

    async def async_set_telegram_notify_unavailable(self, enabled: bool) -> None:
        self.telegram_notify_unavailable = enabled
        await self._async_save()
        self._notify_entities()

    def _zone_display_name(self, zone_id: str) -> str:
        from homeassistant.helpers import device_registry as dr
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_{zone_id}")}
        )
        return (device.name_by_user or device.name) if device else zone_id

    async def _async_send_telegram(self, message: str) -> None:
        if not self.telegram_enabled or not self.telegram_chat_id:
            return
        target = self.telegram_chat_id
        try:
            if target.startswith("notify."):
                service_name = target[len("notify."):]
                if service_name in self.hass.services.async_services().get("notify", {}):
                    await self.hass.services.async_call(
                        "notify", service_name, {"message": message}, blocking=False
                    )
                else:
                    await self.hass.services.async_call(
                        "notify", "send_message",
                        {"entity_id": target, "message": message},
                        blocking=False,
                    )
            else:
                await self.hass.services.async_call(
                    "telegram_bot", "send_message",
                    {"message": message, "target": target},
                    blocking=False,
                )
        except Exception as exc:
            _LOGGER.warning("IrriSynk: Telegram notification failed: %s", exc)

    async def _async_save_and_refresh(self) -> None:
        await self._async_save()
        await self.async_request_refresh()

    # ------------------------------------------------------------------
    # Drip calculator
    # ------------------------------------------------------------------

    async def async_run_calculator(self) -> None:
        """Compute mm/m²/h from dripper flow and spacing, then refresh entities."""
        esp_g = self.forms.calc_dripper_spacing_cm / 100.0
        esp_l = self.forms.calc_line_spacing_cm / 100.0
        if esp_g > 0 and esp_l > 0:
            self.forms.calc_result_mm_h = round(self.forms.calc_flow_lh / (esp_g * esp_l), 2)
        else:
            self.forms.calc_result_mm_h = None
        self._notify_entities()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cfg(self, key: str, default: str = "") -> str:
        return self.entry.options.get(key, self.entry.data.get(key, default)) or default

    def _cfg_sensor(self, key: str) -> str | None:
        val = self.entry.options.get(key, self.entry.data.get(key, ""))
        return (val or "").strip() or None

    def _get_entity_float(self, entity_id: str) -> float | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        return _safe_float(state.state)

    def _get_latitude(self) -> float:
        configured = self.entry.options.get(CONF_LATITUDE, self.entry.data.get(CONF_LATITUDE))
        if configured is not None:
            return float(configured)
        return float(getattr(self.hass.config, "latitude", 44.5) or 44.5)

    def _is_english(self) -> bool:
        configured = self.entry.options.get(CONF_DASHBOARD_LANGUAGE, "auto")
        if configured == DASHBOARD_LANGUAGE_EN:
            return True
        if configured == DASHBOARD_LANGUAGE_FR:
            return False
        lang = str(getattr(self.hass.config, "language", "en")).lower()
        return not lang.startswith("fr")


def _safe_float(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


