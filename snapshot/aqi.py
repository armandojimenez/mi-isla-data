"""US EPA Air Quality Index from pollutant concentrations.

Breakpoints follow 40 CFR Part 58, Appendix G, with the PM2.5 table EPA
revised in 2024 (Good now ends at 9.0 ug/m3). Concentrations arrive from the
model in ug/m3 and are converted to the ppm/ppb units the gas tables use, at
25 C and 1 atm (24.45 L/mol).
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

# (C_low, C_high, I_low, I_high) per pollutant, ascending.
BREAKPOINTS: dict[str, list[tuple[float, float, int, int]]] = {
    "pm25_24h": [
        (0.0, 9.0, 0, 50),
        (9.1, 35.4, 51, 100),
        (35.5, 55.4, 101, 150),
        (55.5, 125.4, 151, 200),
        (125.5, 225.4, 201, 300),
        (225.5, 325.4, 301, 500),
    ],
    "pm10_24h": [
        (0, 54, 0, 50),
        (55, 154, 51, 100),
        (155, 254, 101, 150),
        (255, 354, 151, 200),
        (355, 424, 201, 300),
        (425, 604, 301, 500),
    ],
    # ppm. The 8-hour table stops at 0.200 ppm; above that only 1-hour applies.
    "o3_8h": [
        (0.000, 0.054, 0, 50),
        (0.055, 0.070, 51, 100),
        (0.071, 0.085, 101, 150),
        (0.086, 0.105, 151, 200),
        (0.106, 0.200, 201, 300),
    ],
    # ppm. Only defined from 0.125 ppm up.
    "o3_1h": [
        (0.125, 0.164, 101, 150),
        (0.165, 0.204, 151, 200),
        (0.205, 0.404, 201, 300),
        (0.405, 0.604, 301, 500),
    ],
    # ppb.
    "no2_1h": [
        (0, 53, 0, 50),
        (54, 100, 51, 100),
        (101, 360, 101, 150),
        (361, 649, 151, 200),
        (650, 1249, 201, 300),
        (1250, 2049, 301, 500),
    ],
    # ppb. EPA switches to the 24-hour mean at 305 ppb; the 1-hour value is a
    # conservative stand-in there and never occurs over Puerto Rico.
    "so2_1h": [
        (0, 35, 0, 50),
        (36, 75, 51, 100),
        (76, 185, 101, 150),
        (186, 304, 151, 200),
        (305, 604, 201, 300),
        (605, 1004, 301, 500),
    ],
    # ppm.
    "co_8h": [
        (0.0, 4.4, 0, 50),
        (4.5, 9.4, 51, 100),
        (9.5, 12.4, 101, 150),
        (12.5, 15.4, 151, 200),
        (15.5, 30.4, 201, 300),
        (30.5, 50.4, 301, 500),
    ],
}

# Decimal places each table is truncated to before lookup (EPA rule).
TRUNCATE: dict[str, int] = {
    "pm25_24h": 1,
    "pm10_24h": 0,
    "o3_8h": 3,
    "o3_1h": 3,
    "no2_1h": 0,
    "so2_1h": 0,
    "co_8h": 1,
}

MOLAR_VOLUME = 24.45  # L/mol at 25 C, 1 atm
MOLAR_MASS = {"o3": 48.00, "no2": 46.01, "so2": 64.07, "co": 28.01}


def ugm3_to_ppb(value: float, gas: str) -> float:
    return value * MOLAR_VOLUME / MOLAR_MASS[gas]


def ugm3_to_ppm(value: float, gas: str) -> float:
    return ugm3_to_ppb(value, gas) / 1000.0


def _truncate(value: float, places: int) -> float:
    factor = 10**places
    # A tiny epsilon keeps 9.0000001 from flooring to 8.9 through float error.
    return math.floor(value * factor + 1e-9) / factor


def sub_index(table: str, concentration: float | None) -> int | None:
    """The AQI sub-index for one pollutant, or None when it can't be rated."""
    if concentration is None or math.isnan(concentration):
        return None
    c = _truncate(max(concentration, 0.0), TRUNCATE[table])
    bands = BREAKPOINTS[table]
    if c < bands[0][0]:
        return None  # below a table's floor (only the 1-hour ozone table)
    for c_lo, c_hi, i_lo, i_hi in bands:
        if c_lo <= c <= c_hi:
            return round((i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo)
    return 500  # beyond the top of the scale


def rolling_mean(values: Sequence[float], hours: int) -> list[float]:
    """Trailing mean over the last `hours` values (NaNs skipped)."""
    out: list[float] = []
    for i in range(len(values)):
        window = [v for v in values[max(0, i - hours + 1) : i + 1] if not math.isnan(v)]
        out.append(sum(window) / len(window) if window else math.nan)
    return out


def us_aqi_series(
    pm25: Sequence[float],
    pm10: Sequence[float],
    o3: Sequence[float],
    no2: Sequence[float],
    so2: Sequence[float],
    co: Sequence[float],
) -> list[int | None]:
    """Hourly US AQI from hourly ug/m3 series, all on the same time axis.

    PM uses 24-hour trailing means, ozone and CO 8-hour means, NO2 and SO2
    the hourly value; the index is the worst sub-index (EPA's rule).
    """
    pm25_24 = rolling_mean(pm25, 24)
    pm10_24 = rolling_mean(pm10, 24)
    o3_8 = rolling_mean(o3, 8)
    co_8 = rolling_mean(co, 8)
    out: list[int | None] = []
    for i in range(len(pm25)):
        indices: Iterable[int | None] = (
            sub_index("pm25_24h", pm25_24[i]),
            sub_index("pm10_24h", pm10_24[i]),
            _ozone_index(o3_8[i], o3[i]),
            sub_index("no2_1h", _ppb(no2[i], "no2")),
            sub_index("so2_1h", _ppb(so2[i], "so2")),
            sub_index("co_8h", _ppm(co_8[i], "co")),
        )
        rated = [x for x in indices if x is not None]
        out.append(max(rated) if rated else None)
    return out


def _ppb(value: float, gas: str) -> float:
    return math.nan if math.isnan(value) else ugm3_to_ppb(value, gas)


def _ppm(value: float, gas: str) -> float:
    return math.nan if math.isnan(value) else ugm3_to_ppm(value, gas)


def _ozone_index(mean_8h_ugm3: float, hourly_ugm3: float) -> int | None:
    eight = _ppm(mean_8h_ugm3, "o3")
    one = _ppm(hourly_ugm3, "o3")
    candidates = []
    if not math.isnan(eight) and _truncate(eight, 3) <= 0.200:
        candidates.append(sub_index("o3_8h", eight))
    if not math.isnan(one):
        candidates.append(sub_index("o3_1h", one))
    rated = [x for x in candidates if x is not None]
    return max(rated) if rated else None
