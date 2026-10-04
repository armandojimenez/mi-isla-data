import datetime as dt

import numpy as np
import pytest

from snapshot.build import SnapshotError, _current_index, validate_air
from snapshot.series import HOUR, interpolate, iso, rounded, step_sample, stitch


def test_stitch_keeps_only_older_points_from_history():
    times, values = stitch(
        np.array([10, 20]), np.array([1.0, 2.0]), np.array([0, 10, 20]), np.array([9.0, 9.0, 9.0])
    )
    assert times.tolist() == [0, 10, 20]
    assert values.tolist() == [9.0, 1.0, 2.0]


def test_interpolate_fills_between_three_hourly_points_only():
    times = np.array([0, 3 * HOUR])
    axis = np.array([0, HOUR, 2 * HOUR, 3 * HOUR, 4 * HOUR])
    out = interpolate(times, np.array([0.0, 3.0]), axis)
    assert out[:4].tolist() == [0.0, 1.0, 2.0, 3.0]
    assert np.isnan(out[4])


def test_step_sample_never_blends_directions():
    times = np.array([0, HOUR])
    axis = np.array([0, HOUR // 2, HOUR, 5 * HOUR])
    out = step_sample(times, np.array([350.0, 10.0]), axis)
    assert out[:3].tolist() == [350.0, 350.0, 10.0]
    assert np.isnan(out[3])  # too old to carry forward


def test_rounded_turns_nan_into_null_and_zero_places_into_ints():
    assert rounded([1.26, float("nan"), 2.0], 1) == [1.3, None, 2.0]
    assert rounded([359.6], 0) == [360]


def _air_doc(count=3, aqi_now=40):
    return {
        "kind": "air",
        "start": iso(0),
        "stepSeconds": HOUR,
        "count": count,
        "cells": [
            {
                "aqi": [30, aqi_now, 50],
                "pm25": [1.0, 2.0, 3.0],
                "pm10": [1.0, 2.0, 3.0],
                "o3": [1.0, 2.0, 3.0],
                "no2": [1.0, 2.0, 3.0],
                "dust": [0.0, 1.0, 2.0],
            }
        ],
    }


def test_validation_accepts_a_doc_that_covers_now():
    validate_air(_air_doc(), dt.datetime.fromtimestamp(HOUR + 5, dt.timezone.utc))


def test_validation_rejects_a_doc_that_has_run_out():
    with pytest.raises(SnapshotError):
        _current_index(_air_doc(), dt.datetime.fromtimestamp(10 * HOUR, dt.timezone.utc))


def test_validation_rejects_impossible_values():
    with pytest.raises(SnapshotError):
        validate_air(_air_doc(aqi_now=900), dt.datetime.fromtimestamp(HOUR, dt.timezone.utc))


def test_a_wave_train_the_model_does_not_resolve_is_published_as_missing():
    from snapshot.build import _drop_absent_partitions

    entry = {}
    for prefix in ("windWave", "swell", "secondarySwell"):
        entry[f"{prefix}Height"] = [0.5, 0.0]
        entry[f"{prefix}Direction"] = [90, 0]
        entry[f"{prefix}Period"] = [6.0, 0.0]
    _drop_absent_partitions(entry)
    assert entry["swellHeight"] == [0.5, None]
    assert entry["swellDirection"] == [90, None]
    assert entry["secondarySwellPeriod"] == [6.0, None]
