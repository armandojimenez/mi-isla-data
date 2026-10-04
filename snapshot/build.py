"""Builds Mi Isla's data snapshots: air quality + Saharan dust, and waves.

Run `python -m snapshot.build --out site`. Each domain is built, checked,
and written to `site/v1/<domain>.json`. A domain that fails keeps serving
its last published file, so one bad model run never blanks the app.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import shutil
import sys
import urllib.request
from pathlib import Path

import numpy as np

from . import config
from .aqi import us_aqi_series
from .openmeteo import Field, Run, complete_runs, read_box
from .series import (
    HOUR,
    floor_hour,
    hourly_axis,
    interpolate,
    iso,
    rounded,
    step_sample,
    stitch,
)

log = logging.getLogger("snapshot")

SCHEMA_VERSION = 1
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class SnapshotError(RuntimeError):
    """The model data can't make a trustworthy snapshot."""


# --- Air quality + dust. ---


def build_air(fs, now: dt.datetime) -> dict:
    variables = list(config.AIR_VARIABLES)
    runs = list(complete_runs(fs, config.AIR_MODEL, variables, now))
    if not runs:
        raise SnapshotError("no complete CAMS run in the last three days")
    latest = runs[0]
    # A run from a day earlier supplies the past hours (the AQI trend and the
    # 24-hour PM averages need them); fall back to any older run.
    history = next(
        (r for r in runs[1:] if r.reference <= latest.reference - dt.timedelta(hours=24)),
        runs[1] if len(runs) > 1 else None,
    )
    log.info("air: run %s, history %s", latest.label, history.label if history else "none")

    fields = {v: read_box(fs, latest, v, config.AIR_LATS, config.AIR_LONS) for v in variables}
    past = (
        {v: read_box(fs, history, v, config.AIR_LATS, config.AIR_LONS) for v in variables}
        if history
        else {}
    )
    _same_box(list(fields.values()) + list(past.values()))

    first = min(int(f.times[0]) for f in (list(past.values()) or list(fields.values())))
    last = max(int(f.times[-1]) for f in fields.values())
    axis = hourly_axis(first, last)
    start = max(int(axis[0]), floor_hour(int(now.timestamp())) - config.AIR_PAST_HOURS * HOUR)
    window = axis >= start

    shape = fields["pm2_5"].values.shape
    reference = fields["pm2_5"]
    cells = []
    for row in range(shape[0]):
        for col in range(shape[1]):
            series = {}
            for variable, key in config.AIR_VARIABLES.items():
                field = fields[variable]
                times, values = field.times, field.values[row, col, :].astype(np.float64)
                if variable in past:
                    older = past[variable]
                    times, values = stitch(
                        times, values, older.times, older.values[row, col, :].astype(np.float64)
                    )
                series[key] = np.clip(interpolate(times, values, axis), 0, None)
            aqi = us_aqi_series(
                *(series[k].tolist() for k in ("pm25", "pm10", "o3", "no2", "so2", "co"))
            )
            cell = {
                "lat": round(reference.lat(row), 2),
                "lon": round(reference.lon(col), 2),
                "aqi": [a for a, keep in zip(aqi, window) if keep],
            }
            for key in config.AIR_PUBLISHED:
                cell[key] = rounded(series[key][window], 1)
            cells.append(cell)

    return {
        "v": SCHEMA_VERSION,
        "kind": "air",
        "generatedAt": iso(now),
        "model": config.AIR_MODEL,
        "run": latest.label,
        "attribution": config.ATTRIBUTION["air"],
        "start": iso(int(axis[window][0])),
        "stepSeconds": HOUR,
        "count": int(window.sum()),
        "units": {key: "ug/m3" for key in config.AIR_PUBLISHED},
        "cells": cells,
    }


def validate_air(doc: dict, now: dt.datetime) -> None:
    count = doc["count"]
    current = _current_index(doc, now)
    cells = doc["cells"]
    if not cells:
        raise SnapshotError("air: no cells")
    rated_now = 0
    for cell in cells:
        for key in ("aqi", *config.AIR_PUBLISHED):
            if len(cell[key]) != count:
                raise SnapshotError(f"air: {key} has {len(cell[key])} of {count} values")
        _check_range(cell["aqi"], 0, 500, "aqi")
        _check_range(cell["pm25"], 0, 1000, "pm25")
        _check_range(cell["pm10"], 0, 3000, "pm10")
        _check_range(cell["dust"], 0, 5000, "dust")
        if cell["aqi"][current] is not None and cell["dust"][current] is not None:
            rated_now += 1
    if rated_now < len(cells) / 2:
        raise SnapshotError(f"air: only {rated_now} of {len(cells)} cells cover now")


# --- Waves. ---


def build_marine(fs, now: dt.datetime) -> dict:
    variables = list(config.MARINE_VARIABLES)
    run = next(complete_runs(fs, config.MARINE_MODEL, variables, now), None)
    if run is None:
        raise SnapshotError("no complete GFS-Wave run in the last three days")
    log.info("marine: run %s", run.label)

    fields = {
        v: read_box(fs, run, v, config.MARINE_LATS, config.MARINE_LONS) for v in variables
    }
    _same_box(list(fields.values()))

    hour = floor_hour(int(now.timestamp()))
    axis = hourly_axis(
        hour - config.MARINE_PAST_HOURS * HOUR, hour + config.MARINE_AHEAD_HOURS * HOUR
    )
    heights = fields["wave_height"]
    spots = []
    for spot_id, lat, lon in config.SPOTS:
        cell = _wet_cell(heights, lat, lon, axis)
        if cell is None:
            log.warning("marine: no wet cell near %s", spot_id)
            continue
        row, col = cell
        entry = {
            "id": spot_id,
            "lat": lat,
            "lon": lon,
            "cellLat": round(heights.lat(row), 3),
            "cellLon": round(heights.lon(col), 3),
        }
        for variable, (key, places) in config.MARINE_VARIABLES.items():
            field = fields[variable]
            values = step_sample(field.times, field.values[row, col, :].astype(np.float64), axis)
            if key.endswith("Direction"):
                values = np.mod(values, 360.0)
            else:
                values = np.clip(values, 0, None)
            entry[key] = rounded(values, places)
            if key.endswith("Direction"):
                entry[key] = [None if d is None else d % 360 for d in entry[key]]
        _drop_absent_partitions(entry)
        spots.append(entry)

    return {
        "v": SCHEMA_VERSION,
        "kind": "marine",
        "generatedAt": iso(now),
        "model": config.MARINE_MODEL,
        "run": run.label,
        "attribution": config.ATTRIBUTION["marine"],
        "start": iso(int(axis[0])),
        "stepSeconds": HOUR,
        "count": int(axis.size),
        "units": {"height": "m", "period": "s", "direction": "deg (from)"},
        "spots": spots,
    }


def validate_marine(doc: dict, now: dt.datetime) -> None:
    count = doc["count"]
    current = _current_index(doc, now)
    spots = doc["spots"]
    if len(spots) < len(config.SPOTS) - 2:
        raise SnapshotError(f"marine: only {len(spots)} of {len(config.SPOTS)} spots")
    for spot in spots:
        for key, _ in config.MARINE_VARIABLES.values():
            if len(spot[key]) != count:
                raise SnapshotError(f"marine: {spot['id']} {key} has {len(spot[key])} values")
            if key.endswith("Height"):
                _check_range(spot[key], 0, 30, key)
            elif key.endswith("Period"):
                _check_range(spot[key], 0, 40, key)
            else:
                _check_range(spot[key], 0, 359, key)
        if spot["waveHeight"][current] is None:
            raise SnapshotError(f"marine: {spot['id']} has no wave height now")


def _drop_absent_partitions(entry: dict) -> None:
    """A wave train the model doesn't resolve comes back as zeros; publish it
    as missing, so the app hides it instead of showing a made-up 0 m swell."""
    for prefix in ("windWave", "swell", "secondarySwell"):
        heights = entry[f"{prefix}Height"]
        for index, height in enumerate(heights):
            if height is None or height < 0.01:
                for suffix in ("Height", "Direction", "Period"):
                    entry[f"{prefix}{suffix}"][index] = None


def _wet_cell(field: Field, lat: float, lon: float, axis: np.ndarray) -> tuple[int, int] | None:
    """The nearest grid cell to a spot that holds sea values over the axis."""
    rows, cols = field.values.shape[:2]
    candidates = []
    for row in range(rows):
        for col in range(cols):
            km = _km(lat, lon, field.lat(row), field.lon(col))
            if km <= config.MARINE_MAX_CELL_KM:
                candidates.append((km, row, col))
    for _, row, col in sorted(candidates):
        sampled = step_sample(field.times, field.values[row, col, :].astype(np.float64), axis)
        if np.isfinite(sampled).mean() >= 0.9:
            return row, col
    return None


# --- Shared checks. ---


def _same_box(fields: list[Field]) -> None:
    first = fields[0]
    for field in fields[1:]:
        if (
            field.lat_offset != first.lat_offset
            or field.lon_offset != first.lon_offset
            or field.values.shape[:2] != first.values.shape[:2]
        ):
            raise SnapshotError("variables don't share one grid box")


def _current_index(doc: dict, now: dt.datetime) -> int:
    start = dt.datetime.strptime(doc["start"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )
    index = int((floor_hour(int(now.timestamp())) - int(start.timestamp())) // doc["stepSeconds"])
    if not 0 <= index < doc["count"]:
        raise SnapshotError(f"{doc['kind']}: the series doesn't cover now")
    return index


def _check_range(values: list, low: float, high: float, what: str) -> None:
    for value in values:
        if value is not None and not (low <= value <= high):
            raise SnapshotError(f"{what} out of range: {value}")


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


# --- Publishing. ---


def write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=True), encoding="utf-8")


def keep_live_copy(kind: str, target: Path) -> bool:
    """Re-publish the file that's live now, so a failed build changes nothing."""
    url = f"{config.PUBLIC_BASE}v1/{kind}.json"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "mi-isla-data"})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        doc = json.loads(body)
        if doc.get("kind") != kind or doc.get("v") != SCHEMA_VERSION:
            return False
    except Exception as error:  # noqa: BLE001 - any failure means "nothing to keep"
        log.warning("%s: no live copy to keep (%s)", kind, error)
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="site", help="output directory")
    parser.add_argument("--now", help="pretend it is this UTC time (ISO 8601)")
    parser.add_argument("--only", choices=("air", "marine"), help="build one domain")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    now = (
        dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
        if args.now
        else dt.datetime.now(dt.timezone.utc)
    ).replace(microsecond=0)

    import fsspec  # imported late so the pure modules stay test-friendly

    fs = fsspec.filesystem("s3", anon=True)
    out = Path(args.out)
    domains = (("air", build_air, validate_air), ("marine", build_marine, validate_marine))
    status: dict = {"generatedAt": iso(now), "domains": {}}
    published = 0
    for kind, build, validate in domains:
        if args.only and kind != args.only:
            continue
        target = out / "v1" / f"{kind}.json"
        try:
            doc = build(fs, now)
            validate(doc, now)
            write_json(target, doc)
            status["domains"][kind] = {"ok": True, "run": doc["run"]}
            published += 1
            log.info("%s: published (%d bytes)", kind, target.stat().st_size)
        except Exception as error:  # noqa: BLE001 - one domain must not sink the other
            log.exception("%s: build failed", kind)
            kept = keep_live_copy(kind, target)
            status["domains"][kind] = {"ok": False, "error": str(error)[:300], "kept": kept}
            published += int(kept)

    write_json(out / "v1" / "status.json", status)
    if STATIC_DIR.is_dir():
        shutil.copytree(STATIC_DIR, out, dirs_exist_ok=True)
    return 0 if published else 1


if __name__ == "__main__":
    sys.exit(main())
