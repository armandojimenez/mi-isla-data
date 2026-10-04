"""Small, pure helpers for putting model output on one hourly time axis."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

HOUR = 3600


def floor_hour(epoch_seconds: int) -> int:
    return epoch_seconds - epoch_seconds % HOUR


def hourly_axis(start: int, end: int) -> np.ndarray:
    """Epoch seconds from `start` to `end` inclusive, one per hour."""
    return np.arange(floor_hour(start), end + 1, HOUR, dtype=np.int64)


def stitch(
    times: np.ndarray,
    values: np.ndarray,
    history_times: np.ndarray | None,
    history_values: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Prepend an older run's points from before the newer run begins."""
    if history_times is None or history_values is None or times.size == 0:
        return times, values
    earlier = history_times < times[0]
    return (
        np.concatenate([history_times[earlier], times]),
        np.concatenate([history_values[earlier], values]),
    )


def interpolate(times: np.ndarray, values: np.ndarray, axis: np.ndarray) -> np.ndarray:
    """Linear interpolation onto `axis`; NaN outside the span of real values."""
    out = np.full(axis.shape, np.nan, dtype=np.float64)
    finite = np.isfinite(values)
    if not finite.any():
        return out
    t = times[finite]
    v = values[finite].astype(np.float64)
    inside = (axis >= t[0]) & (axis <= t[-1])
    out[inside] = np.interp(axis[inside], t, v)
    return out


def step_sample(
    times: np.ndarray, values: np.ndarray, axis: np.ndarray, max_age: int = 3 * HOUR
) -> np.ndarray:
    """The latest model value at or before each axis time (no blending).

    Used for wave fields, whose directions must never be averaged across the
    0/360 seam. A value older than `max_age` doesn't carry forward.
    """
    out = np.full(axis.shape, np.nan, dtype=np.float64)
    if times.size == 0:
        return out
    index = np.searchsorted(times, axis, side="right") - 1
    valid = (index >= 0) & (axis - times[np.clip(index, 0, None)] <= max_age)
    out[valid] = values[index[valid]]
    return out


def rounded(values, places: int) -> list:
    """JSON-ready numbers: NaN becomes null, places=0 gives ints."""
    out = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            out.append(None)
        elif places == 0:
            out.append(int(round(number)))
        else:
            out.append(round(number, places))
    return out


def iso(epoch_seconds: int | float | dt.datetime) -> str:
    if isinstance(epoch_seconds, dt.datetime):
        moment = epoch_seconds.astimezone(dt.timezone.utc)
    else:
        moment = dt.datetime.fromtimestamp(int(epoch_seconds), tz=dt.timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
