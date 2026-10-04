"""Reads model runs from Open-Meteo's open data on AWS (s3://openmeteo).

The bucket holds each model run as one `.om` file per variable, laid out as
`data_run/<model>/<YYYY>/<MM>/<DD>/<HHMM>Z/<variable>.om` next to a
`meta.json`. Every array is (latitude, longitude, time) on a regular
lat/lon grid whose bounds are written in the file's CRS. The data is
licensed CC BY 4.0 by Open-Meteo; see the README for attribution.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Iterator

import numpy as np
from omfiles import OmFileReader

BUCKET = "openmeteo"
_RUN_PATTERN = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/(\d{2})(\d{2})Z$")
_BBOX_PATTERN = re.compile(r"BBOX\[([^\]]+)\]")


@dataclass(frozen=True)
class Grid:
    """A regular lat/lon grid, inclusive of both bounds."""

    lat_min: float
    lon_min: float
    lat_max: float
    lon_max: float
    n_lat: int
    n_lon: int

    @property
    def dlat(self) -> float:
        return (self.lat_max - self.lat_min) / (self.n_lat - 1)

    @property
    def dlon(self) -> float:
        return (self.lon_max - self.lon_min) / (self.n_lon - 1)

    def lat_index(self, lat: float) -> int:
        return min(max(round((lat - self.lat_min) / self.dlat), 0), self.n_lat - 1)

    def lon_index(self, lon: float) -> int:
        return min(max(round((lon - self.lon_min) / self.dlon), 0), self.n_lon - 1)

    def lat_at(self, index: int) -> float:
        return self.lat_min + index * self.dlat

    def lon_at(self, index: int) -> float:
        return self.lon_min + index * self.dlon


@dataclass
class Field:
    """One variable over a lat/lon box: values[lat, lon, time]."""

    grid: Grid
    lat_offset: int
    lon_offset: int
    times: np.ndarray  # epoch seconds, int64
    values: np.ndarray  # float32, NaN where the model has no value

    def lat(self, row: int) -> float:
        return self.grid.lat_at(self.lat_offset + row)

    def lon(self, col: int) -> float:
        return self.grid.lon_at(self.lon_offset + col)


@dataclass(frozen=True)
class Run:
    model: str
    path: str  # bucket path, e.g. openmeteo/data_run/cams_global/2026/10/03/1200Z
    reference: dt.datetime  # UTC

    @property
    def label(self) -> str:
        return self.reference.strftime("%Y-%m-%dT%H:%MZ")


def run_from_path(model: str, path: str) -> Run | None:
    match = _RUN_PATTERN.search(path.rstrip("/"))
    if not match:
        return None
    year, month, day, hour, minute = (int(x) for x in match.groups())
    reference = dt.datetime(year, month, day, hour, minute, tzinfo=dt.timezone.utc)
    return Run(model=model, path=path.rstrip("/"), reference=reference)


def complete_runs(
    fs, model: str, variables: list[str], now: dt.datetime, days: int = 3
) -> Iterator[Run]:
    """Runs of `model` that already hold every variable, newest first.

    A run directory fills in variable by variable while Open-Meteo converts
    it, so a run only counts once `meta.json` and all `variables` are there.
    """
    for back in range(days):
        day = (now - dt.timedelta(days=back)).strftime("%Y/%m/%d")
        try:
            entries = fs.ls(f"{BUCKET}/data_run/{model}/{day}/", detail=False)
        except FileNotFoundError:
            continue
        runs = [run_from_path(model, e) for e in entries]
        for run in sorted((r for r in runs if r), key=lambda r: r.reference, reverse=True):
            if run.reference > now:
                continue
            names = {p.rstrip("/").rsplit("/", 1)[-1] for p in fs.ls(run.path, detail=False)}
            if "meta.json" in names and all(f"{v}.om" in names for v in variables):
                yield run


def grid_of(reader: OmFileReader) -> Grid:
    crs = reader.get_child_by_name("crs_wkt").read_scalar()
    match = _BBOX_PATTERN.search(crs)
    if not match:
        raise ValueError("the file has no BBOX in its CRS")
    lat_min, lon_min, lat_max, lon_max = (float(x) for x in match.group(1).split(","))
    n_lat, n_lon, _ = reader.shape
    return Grid(lat_min, lon_min, lat_max, lon_max, n_lat, n_lon)


def read_box(
    fs,
    run: Run,
    variable: str,
    lat_range: tuple[float, float],
    lon_range: tuple[float, float],
) -> Field:
    reader = OmFileReader.from_fsspec(fs, f"{run.path}/{variable}.om")
    try:
        grid = grid_of(reader)
        y0, y1 = sorted(grid.lat_index(lat) for lat in lat_range)
        x0, x1 = sorted(grid.lon_index(lon) for lon in lon_range)
        values = np.asarray(reader[y0 : y1 + 1, x0 : x1 + 1, :], dtype=np.float32)
        times = np.asarray(reader.get_child_by_name("time")[:], dtype=np.int64)
    finally:
        reader.close()
    if values.shape[2] != times.shape[0]:
        raise ValueError(f"{variable}: {values.shape[2]} values for {times.shape[0]} times")
    return Field(grid=grid, lat_offset=y0, lon_offset=x0, times=times, values=values)
