"""What the snapshot covers. Coordinates are WGS84 decimal degrees."""

from __future__ import annotations

# Where the published files live (GitHub Pages for this repository).
PUBLIC_BASE = "https://armandojimenez.dev/mi-isla-data/"

# --- Air quality + Saharan dust (CAMS global, 0.4 degree grid). ---

AIR_MODEL = "cams_global"

# Open-Meteo variable -> key in the published file.
AIR_VARIABLES = {
    "pm2_5": "pm25",
    "pm10": "pm10",
    "ozone": "o3",
    "nitrogen_dioxide": "no2",
    "sulphur_dioxide": "so2",
    "carbon_monoxide": "co",
    "dust": "dust",
}

# Keys that reach the file (SO2 and CO only feed the AQI).
AIR_PUBLISHED = ("pm25", "pm10", "o3", "no2", "dust")

# The grid rows/columns that cover Puerto Rico, Vieques and Culebra: every
# point of la isla is nearest to one of these 0.4 degree cells.
AIR_LATS = (18.0, 18.4)
AIR_LONS = (-67.2, -65.2)

# Hours of history kept before "now" (the app draws a 24-hour AQI trend).
AIR_PAST_HOURS = 25

# The oldest CAMS run worth publishing. Runs land twice a day about ten hours
# late, so the newest is normally 10 to 25 hours old; past this the model feed
# has stalled, and the last good file (with its honest, aging `generatedAt`)
# stays up instead of an old forecast passing as new.
AIR_MAX_RUN_AGE_HOURS = 30

# --- Waves (NOAA GFS-Wave, 1/6 degree Atlantic grid). ---

MARINE_MODEL = "ncep_gfswave016"

# Open-Meteo variable -> (key in the published file, decimal places).
MARINE_VARIABLES = {
    "wave_height": ("waveHeight", 2),
    "wave_direction": ("waveDirection", 0),
    "wave_period": ("wavePeriod", 1),
    "wind_wave_height": ("windWaveHeight", 2),
    "wind_wave_direction": ("windWaveDirection", 0),
    "wind_wave_period": ("windWavePeriod", 1),
    "swell_wave_height": ("swellHeight", 2),
    "swell_wave_direction": ("swellDirection", 0),
    "swell_wave_period": ("swellPeriod", 1),
    "secondary_swell_wave_height": ("secondarySwellHeight", 2),
    "secondary_swell_wave_direction": ("secondarySwellDirection", 0),
    "secondary_swell_wave_period": ("secondarySwellPeriod", 1),
}

# The beaches the app reads, each nudged a touch seaward (same coordinates as
# the app's coastal spot list). The nearest wet grid cell stands in for each.
SPOTS = (
    ("isabela", 18.53, -67.05),
    ("arecibo", 18.50, -66.72),
    ("dorado", 18.52, -66.30),
    ("san-juan", 18.48, -66.10),
    ("loiza", 18.46, -65.88),
    ("luquillo", 18.41, -65.72),
    ("aguadilla", 18.47, -67.18),
    ("rincon", 18.35, -67.27),
    ("cabo-rojo", 18.05, -67.21),
    ("guanica", 17.92, -66.91),
    ("ponce", 17.95, -66.62),
    ("salinas", 17.92, -66.28),
    ("patillas", 17.98, -66.01),
    ("fajardo", 18.33, -65.61),
    ("naguabo", 18.19, -65.69),
    ("humacao", 18.13, -65.73),
)

# The box read around the spots, and how far a spot may sit from its cell.
MARINE_LATS = (17.5, 18.9)
MARINE_LONS = (-67.7, -65.3)
MARINE_MAX_CELL_KM = 30.0

# Hours kept around "now": a little history, then three days ahead.
MARINE_PAST_HOURS = 3
MARINE_AHEAD_HOURS = 72

# The oldest GFS-Wave run worth publishing (four runs a day, normally 5 to 14
# hours old when the job runs); see AIR_MAX_RUN_AGE_HOURS.
MARINE_MAX_RUN_AGE_HOURS = 18

ATTRIBUTION = {
    "air": (
        "Contains modified Copernicus Atmosphere Monitoring Service information "
        "(CAMS global forecast), processed by Open-Meteo.com (CC BY 4.0)."
    ),
    "marine": "NOAA GFS-Wave forecast, processed by Open-Meteo.com (CC BY 4.0).",
}
