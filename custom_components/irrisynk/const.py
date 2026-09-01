# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Constants for IrriSynk."""

from datetime import timedelta

DOMAIN = "irrisynk"

PLATFORMS = ["sensor", "select", "date", "switch", "number", "time", "text", "button"]

CONF_WEATHER_ENTITY_ID = "weather_entity_id"
CONF_ZONES = "zones"
CONF_KC_CATALOG_PATH = "kc_catalog_path"
CONF_LATITUDE = "latitude"

# Local sensor corrections (integration-level, all optional)
CONF_WIND_SENSOR = "wind_sensor_entity_id"
CONF_TEMP_MAX_SENSOR = "temp_max_sensor_entity_id"
CONF_TEMP_MIN_SENSOR = "temp_min_sensor_entity_id"
CONF_PRESSURE_SENSOR = "pressure_sensor_entity_id"
CONF_CLOUD_SENSOR = "cloud_sensor_entity_id"

CONF_RAIN_SENSOR = "rain_sensor_entity_id"
CONF_RAIN_SENSOR_MODE = "rain_sensor_mode"

# Optional dedicated entity for rain FORECAST (overrides weather forecast precipitation)
CONF_RAIN_FORECAST_SENSOR = "rain_forecast_sensor_entity_id"

RAIN_SENSOR_MODE_CUMULATIVE = "cumulative"    # value = total since midnight
RAIN_SENSOR_MODE_INCREMENTAL = "incremental"  # value = total since device reset

DEFAULT_NAME = "IrriSynk"
DEFAULT_ZONE_IDS = ["zone_1"]
DEFAULT_KC_CATALOG_PATH = "data/kc_catalog.json"

UPDATE_INTERVAL = timedelta(minutes=15)

STAGE_MODE_MANUAL = "manual"
STAGE_MODE_AUTO_BY_DAYS = "auto_by_days"
STAGE_MODES = [STAGE_MODE_MANUAL, STAGE_MODE_AUTO_BY_DAYS]

ZONE_MODE_MANUAL = "manual"
ZONE_MODE_SCHEDULED = "scheduled"
ZONE_MODE_AUTO = "auto"
ZONE_MODE_MIXED = "mixed"
ZONE_MODES = [ZONE_MODE_MANUAL, ZONE_MODE_SCHEDULED, ZONE_MODE_AUTO]
ZONE_MODES_ALL = [ZONE_MODE_MIXED, ZONE_MODE_MANUAL, ZONE_MODE_SCHEDULED, ZONE_MODE_AUTO]

CULTIVATION_MODE_OPEN_FIELD = "plein_champ"

CULTIVATION_MODES = [
    "plein_champ",
    "serre_hiver",
    "serre_printemps",
    "serre_ete",
    "serre_automne",
    "paillage_leger",
    "paillage_moyen",
    "paillage_epais",
    "toile_film",
]

# Modes that behave like a greenhouse (no rain, greenhouse stage durations)
CULTIVATION_MODES_GREENHOUSE: frozenset[str] = frozenset([
    "serre", "serre_hiver", "serre_printemps", "serre_ete", "serre_automne",
])

# Default ET0 correction factor for each built-in mode
CULTIVATION_MODE_ET0_FACTORS: dict[str, float] = {
    "plein_champ":   1.0,
    "serre_hiver":   0.5,
    "serre_printemps": 0.6,
    "serre_ete":     0.7,
    "serre_automne": 0.6,
    "paillage_leger": 0.9,
    "paillage_moyen": 0.8,
    "paillage_epais": 0.7,
    "toile_film":    0.7,
    "serre":         0.7,  # legacy
}

CONF_DASHBOARD_LANGUAGE = "dashboard_language"
DASHBOARD_LANGUAGE_AUTO = "auto"
DASHBOARD_LANGUAGE_EN = "en"
DASHBOARD_LANGUAGE_FR = "fr"

DEFAULT_ET0_CORRECTION_OPEN_FIELD = 1.0

# Soil type AWC (Available Water Capacity) in mm per meter of soil — FAO-56 Table 19
SOIL_AWC_MM_PER_M: dict[str, int] = {
    "sandy":       75,
    "loamy_sand":  100,
    "sandy_loam":  130,
    "loam":        170,
    "silt_loam":   175,
    "clay_loam":   155,
    "clay":        150,
}
SOIL_TYPES: list[str] = list(SOIL_AWC_MM_PER_M.keys())
SOIL_DEFAULT = "loam"

# FAO-56 RAW fraction (Readily Available Water = p × TAW, p ≈ 0.4 for most crops)
RAW_FRACTION = 0.4
# Minimum effective root depth used at transplanting/germination (cm)
SOIL_INITIAL_ROOT_DEPTH_CM = 15
