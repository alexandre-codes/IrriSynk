# Copyright (C) 2026 Alexandre-Codes
# SPDX-License-Identifier: GPL-3.0-or-later
# See <https://www.gnu.org/licenses/gpl-3.0.html>
"""Irrigation math helpers."""

from __future__ import annotations

import math


def compute_et0_fao56(
    tmax_c: float,
    tmin_c: float,
    wind_kmh: float,
    pressure_hpa: float,
    cloud_cover_pct: float,
    latitude_deg: float,
    doy: int,
) -> float:
    """Compute daily ET0 using FAO-56 Penman-Monteith (eq. 6)."""
    tmean = (tmax_c + tmin_c) / 2
    wind_ms = wind_kmh / 3.6
    pressure = pressure_hpa / 10  # hPa -> kPa

    lat = latitude_deg * math.pi / 180

    # Extra-terrestrial radiation Ra - FAO-56 eq. 21-25
    dr = 1 + 0.033 * math.cos(2 * math.pi / 365 * doy)
    decl = 0.409 * math.sin(2 * math.pi / 365 * doy - 1.39)
    ws_arg = max(-0.9999, min(0.9999, -math.tan(lat) * math.tan(decl)))
    ws = math.acos(ws_arg)
    ra = (24 * 60 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat) * math.sin(decl)
        + math.cos(lat) * math.cos(decl) * math.sin(ws)
    )

    # Solar radiation via cloud fraction (Angstrom-Prescott) - FAO-56 eq. 35
    n_N = 1 - cloud_cover_pct / 100
    rs = (0.25 + 0.50 * n_N) * ra
    rs0 = 0.75 * ra  # clear-sky radiation

    albedo = 0.23
    gamma = 0.000665 * pressure  # psychrometric constant (kPa/°C)

    # Saturation vapour pressure - FAO-56 eq. 11-12
    es_max = 0.6108 * math.exp((17.27 * tmax_c) / (tmax_c + 237.3))
    es_min = 0.6108 * math.exp((17.27 * tmin_c) / (tmin_c + 237.3))
    es = (es_max + es_min) / 2
    ea = es_min  # actual vapour pressure approx (arid) - FAO-56 eq. 48

    # SVP slope at Tmean - FAO-56 eq. 13
    es_tmean = 0.6108 * math.exp((17.27 * tmean) / (tmean + 237.3))
    svp_slope = (4098 * es_tmean) / ((tmean + 237.3) ** 2)

    # Net shortwave radiation - FAO-56 eq. 38
    rns = (1 - albedo) * rs

    # Net longwave radiation - FAO-56 eq. 39
    sigma = 4.903e-9
    tk = tmean + 273.16
    rs_rs0 = min(rs / max(rs0, 0.001), 1.0)
    rnl = sigma * (tk ** 4) * (0.34 - 0.14 * math.sqrt(ea)) * max(1.35 * rs_rs0 - 0.35, 0)

    rn = rns - rnl

    # Penman-Monteith ET0 (mm/day) - FAO-56 eq. 6
    et0 = (
        (0.408 * svp_slope * rn)
        + (gamma * (900 / (tmean + 273)) * wind_ms * (es - ea))
    ) / (svp_slope + gamma * (1 + 0.34 * wind_ms))

    return round(max(0.0, et0), 2)


def compute_water_need_mm(
    et0_mm: float,
    kc: float,
    effective_rain_mm: float,
    soil_buffer_mm: float,
    soil_water_balance_mm: float = 0.0,
) -> float:
    """Compute daily water need in millimeters.

    soil_water_balance_mm > 0: J-1 surplus  → reduces today's need
    soil_water_balance_mm < 0: J-1 deficit  → increases today's need
    """
    value = et0_mm * kc - effective_rain_mm - soil_water_balance_mm - soil_buffer_mm
    return max(0.0, round(value, 2))


def mm_to_minutes(water_need_mm: float, flow_mm_h: float) -> float:
    """Convert water need (mm) to irrigation duration (minutes) given flow in mm/h."""
    if flow_mm_h <= 0:
        return 0.0
    return round(water_need_mm / flow_mm_h * 60, 1)
