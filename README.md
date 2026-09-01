🇬🇧 **English** | 🇫🇷 [Français](README.fr.md)

---

# IrriSynk

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
![version](https://img.shields.io/badge/version-0.1.0-blue)
![HA min version](https://img.shields.io/badge/HA-2024.3%2B-blue)
![license](https://img.shields.io/badge/license-GPL--3.0-green)

**IrriSynk** is a Home Assistant integration for **smart irrigation control via solenoid valves**.

Every day, for each zone, it calculates the exact amount of water needed using the scientific **FAO-56** method (simplified Penman-Monteith), then **automatically drives the solenoid valves** at the scheduled time — for the precise calculated or fixed duration.

Today's rainfall, yesterday's water balance, growth stage, soil type, cultivation mode: everything is taken into account. If rainfall is sufficient, watering is skipped. Surplus or deficit accumulates in a cumulative water balance, bounded by the soil's readily available water reserve.

> Three modes per zone — **Manual**, **Scheduled** or **Auto** —, a **cascade** mode to chain zones sequentially, and an auto-generated Lovelace dashboard to control everything without touching YAML.

---

## Key Features

- [Water Needs Calculation (FAO-56)](#water-needs-calculation)
- [Soil Water Model (RAW/TAW)](#soil-water-model)
- [Solenoid Valve Control](#solenoid-valve-control)
- [Three Operating Modes per Zone](#three-operating-modes-per-zone)
- [Cascade Irrigation](#cascade-irrigation)
- [Time Scheduling](#time-scheduling)
- [Daily Water Balance](#daily-water-balance)
- [Crops and Growth Stages](#crops-and-growth-stages)
- [Cultivation Modes](#cultivation-modes)
- [Automatic Lovelace Dashboard](#automatic-lovelace-dashboard)
- [Other Features](#other-features)

---

### Water Needs Calculation
- Automatic water need calculation per zone using the FAO-56 formula:  
  `ET₀ × Kc − Effective Rain − Today's Irrigation − Water Balance − Soil Buffer`
- ET₀ calculated from an HA weather entity or local sensors (temperature, wind, pressure, cloud cover)
- Previous day's water balance recalculated at midnight from sensor and valve history
- Rain forecast support from weather entity or a dedicated sensor
- Built-in catalog of 32 crops with FAO-56 Kc coefficients and root depths

### Soil Water Model
- **Soil type** configurable per zone (7 FAO-56 classes: Sand, Loamy sand, Sandy loam, Loam, Silt loam, Clay loam, Clay)
- **Readily Available Water (RAW)** calculation: `RAW = 0.4 × AWC × effective_depth`
- **Progressive** root depth across growth stages: weighted by cumulative durations, from 15 cm (planting) to the crop's FAO-56 depth
- **Dynamic** water balance bounds `[−RAW ; +RAW]` — adapt to the current crop and stage
- **Soil Capacity (RAW)** sensor showing the current reserve in mm
- **Reset** button for the water balance

### Solenoid Valve Control
- Each zone is linked to a Home Assistant **switch** or **valve** entity
- Opening and closing are triggered automatically based on mode and scheduled time
- Automatic recovery on restart: ongoing irrigation is re-armed, overdue irrigation is stopped

### Three Operating Modes per Zone

| Mode | Description |
|---|---|
| **Manual** | No automatic irrigation — the zone is managed manually |
| **Scheduled** | The valve opens at the set time for a fixed duration |
| **Auto** | The valve opens at the set time for the FAO-56 calculated duration (zero if rainfall is sufficient) |

### Cascade Irrigation
- A **cascade** mode waters all eligible zones sequentially from a single global start time
- Zones start one after another with a 1-minute gap
- If a zone finishes early, the schedule of the following zones is recalculated dynamically
- Compatible with per-zone Auto and Scheduled modes

### Time Scheduling
- Configurable start time **per zone** (Auto or Scheduled mode)
- Global **cascade** start time
- The scheduler runs every minute and handles precise starts and stops

### Daily Water Balance
- Every night at midnight, the previous day's actual balance is recalculated:
  - Previous day's ET₀ from sensor history or the forecast value
  - Previous day's rain from rain gauge history or the weather entity
  - Previous day's irrigation from each zone's switch/valve history
- The balance is bounded to `[−RAW ; +RAW]` to avoid unrealistic accumulation
- A cumulative surplus reduces today's need; a deficit increases it

### Crops and Growth Stages
- Built-in catalog of **32 crops** with FAO-56 Kc per stage and root depth (FAO-56, Table 22)
- Manual stage selection or automatic calculation from planting date
- Create custom crops with their own stages, Kc coefficients and root depth
- Edit and delete custom stages from the dashboard

### Cultivation Modes
- Open field, greenhouse (winter/spring/summer/autumn), mulching (light/medium/heavy), row cover/film
- ET₀ correction factor per mode
- Create custom cultivation modes with a free ET₀ factor

### Automatic Lovelace Dashboard
The dashboard is auto-generated and updated in real time. It includes **8 tabs**:

| Tab | Content |
|---|---|
| **Home** | Zone overview: needs, recommended duration, status, weather |
| **Scheduling** | Mode per zone, start time, duration, cascade, water balance |
| **Settings** | Per-zone configuration: valve, flow rate, soil type, crop, stage |
| **Cultivation Modes** | Create and delete custom modes |
| **Crops** | Crop catalog, create/edit/delete crops and stages |
| **Calculator** | Drip flow rate calculator (mm/m²/h) |
| **Statistics** | Water balances, per-zone irrigation history |
| **Wiki** | Built-in documentation: formula, algorithm, FAO-56 reference |

### Other Features
- Multi-zone support (extensible via the `add_zones` service)
- Interface in **French** and **English** (follows the Home Assistant language)
- Dedicated Home Assistant services: recalculation, catalog reload, zone addition
- Full state and settings persistence across restarts

---

## Installation via HACS

1. Open **HACS** in Home Assistant
2. Go to **Integrations** → ⋮ menu → **Custom repositories**
3. Add the URL: `https://github.com/alexandre-codes/irrisynk`  
   Category: **Integration**
4. Search for **IrriSynk** and install
5. Restart Home Assistant
6. Go to **Settings → Devices & Services → Add Integration** → search for **IrriSynk**

---

## Manual Installation

Copy the `custom_components/irrisynk/` folder into the `custom_components/` folder of your Home Assistant configuration, then restart.

---

## Configuration

### Initial Setup (Config Flow)

When adding the integration, provide:
- The Home Assistant **weather entity** used for ET₀ and rain forecast calculations
- The **name** of your installation
- The **latitude** (pre-filled from HA)

### Optional Local Sensors (improved accuracy)

| Sensor | Description |
|---|---|
| Max/min temperature | ET₀ calculation for the previous day from real measurements |
| Wind speed | ET₀ calculation for the previous day from real measurements |
| Atmospheric pressure | ET₀ calculation for the previous day from real measurements |
| Cloud cover | ET₀ calculation for the previous day from real measurements |
| Rain gauge | Actual previous-day rainfall (cumulative or incremental mode) |
| Rain forecast | Replaces the forecast rainfall for today's calculation |

If no local sensor is configured, ET₀ and rainfall come from the weather forecast.

### Zone Configuration

From the dashboard, for each zone:
- Link a **switch or valve entity** (solenoid valve)
- Enter the **flow rate** in mm/h (built-in calculator)
- Choose the **soil type** (7 FAO-56 classes)
- Set the **soil buffer** (mm before triggering)
- Choose the **crop**, the **stage** (or the planting date for auto mode)
- Select the **cultivation mode**
- Set the **operating mode** and **start time**

---

## Calculation Formula

```
Need (mm) = max(0 ; ET₀ × Kc − Effective Rain − Today's Irrigation − Water Balance − Soil Buffer)
Duration (min) = min(Need / Flow Rate × 60 ; Max Duration)
```

| Term | Description |
|---|---|
| **ET₀** | Reference evapotranspiration (FAO-56 Penman-Monteith) |
| **Kc** | Crop coefficient based on the crop and growth stage |
| **Effective Rain** | Precipitation × efficiency rate (default 80%) |
| **Today's Irrigation** | mm already applied today by the valve |
| **Water Balance** | Cumulative surplus or deficit — bounded to `[−RAW ; +RAW]` |
| **RAW** | Readily available water: `0.4 × AWC × effective_root_depth` |
| **Soil Buffer** | Minimum reserve before triggering |

---

## Services

| Service | Description |
|---|---|
| `irrisynk.recalculate_zone` | Recalculates recommendations for a zone |
| `irrisynk.recalculate_all` | Recalculates all zones |
| `irrisynk.reload_kc_catalog` | Reloads the crop catalog from the JSON file |
| `irrisynk.add_zones` | Adds one or more zones (named zone_N+1, zone_N+2…) |

---

## Requirements

- Home Assistant **2024.3+**
- A weather entity configured in Home Assistant
- Switch or valve entities representing the solenoid valves

---

## License

GPL-3.0-or-later — see [LICENSE](LICENSE)
