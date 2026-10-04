import math

import pytest

from snapshot.aqi import rolling_mean, sub_index, ugm3_to_ppb, us_aqi_series


@pytest.mark.parametrize(
    ("table", "concentration", "expected"),
    [
        ("pm25_24h", 0.0, 0),
        ("pm25_24h", 9.0, 50),
        ("pm25_24h", 9.1, 51),
        ("pm25_24h", 9.09, 50),  # truncated to 9.0, never rounded up
        ("pm25_24h", 35.4, 100),
        ("pm25_24h", 35.5, 101),
        ("pm25_24h", 300.0, 449),
        ("pm25_24h", 999.0, 500),
        ("pm10_24h", 54.9, 50),  # truncated to 54
        ("pm10_24h", 155, 101),
        ("o3_8h", 0.054, 50),
        ("o3_8h", 0.0709, 100),  # truncated to 0.070
        ("o3_8h", 0.078, 126),  # EPA's worked example: 125.5 rounds up
        ("o3_8h", 0.072, 105),  # 104.5: halves go up, never to the even 104
        ("o3_1h", 0.100, None),  # the 1-hour table starts at 0.125 ppm
        ("no2_1h", 100, 100),
        ("co_8h", 4.45, 50),  # truncated to 4.4
    ],
)
def test_sub_index_follows_the_epa_tables(table, concentration, expected):
    assert sub_index(table, concentration) == expected


def test_missing_values_are_not_rated():
    assert sub_index("pm25_24h", None) is None
    assert sub_index("pm25_24h", math.nan) is None


def test_rolling_mean_skips_gaps_and_uses_the_trailing_window():
    values = [1.0, math.nan, 3.0, 5.0]
    assert rolling_mean(values, 2) == [1.0, 1.0, 3.0, 4.0]


def test_ppb_conversion_uses_the_molar_volume_at_25c():
    # 1.882 ug/m3 of NO2 is ~1 ppb.
    assert ugm3_to_ppb(46.01, "no2") == pytest.approx(24.45)


def test_aqi_is_the_worst_sub_index():
    hours = 24
    clean = [5.0] * hours
    smoky = [40.0] * hours  # PM2.5 24-hour mean of 40 -> 112
    aqi = us_aqi_series(
        pm25=smoky, pm10=clean, o3=clean, no2=clean, so2=clean, co=[100.0] * hours
    )
    assert aqi[-1] == 112


def test_an_hour_with_no_data_has_no_aqi():
    nan = [math.nan]
    assert us_aqi_series(nan, nan, nan, nan, nan, nan) == [None]


def test_an_average_needs_three_quarters_of_its_hours():
    nan = math.nan
    seventeen = [nan] * 7 + [12.0] * 17
    eighteen = [nan] * 6 + [12.0] * 18
    assert math.isnan(rolling_mean(seventeen, 24, 18)[-1])
    assert rolling_mean(eighteen, 24, 18)[-1] == 12.0


def test_no_index_until_a_pm25_day_is_complete():
    # The first hours of the series hold less than 18 hours of PM2.5, so even
    # with the gases rated they get no index (it would read clean in a dust
    # event); from the 18th hour on, the index stands.
    hours = 30
    dusty = [60.0] * hours  # PM2.5 24-hour mean of 60 -> 154
    gases = [5.0] * hours
    aqi = us_aqi_series(dusty, gases, gases, gases, gases, gases)
    assert aqi[:17] == [None] * 17
    assert aqi[17] == 154
    assert aqi[-1] == 154
