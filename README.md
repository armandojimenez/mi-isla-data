# mi-isla-data

Small, always-current data files for [Mi Isla](https://armandojimenez.dev/apps/mi-isla/),
the Puerto Rico weather app. A scheduled GitHub Actions job reads public model
output, keeps only Puerto Rico, and publishes it to GitHub Pages:

| File | What | Source | Updates |
|---|---|---|---|
| [`v1/air.json`](https://armandojimenez.dev/mi-isla-data/v1/air.json) | US AQI, PM2.5, PM10, ozone, NO₂ and Saharan dust, hourly, from 25 hours ago to ~5 days ahead | CAMS global forecast | twice a day |
| [`v1/marine.json`](https://armandojimenez.dev/mi-isla-data/v1/marine.json) | Waves, wind sea and two swell trains at 16 beaches, hourly, 3 hours back to 3 days ahead | NOAA GFS-Wave | four times a day |
| [`v1/status.json`](https://armandojimenez.dev/mi-isla-data/v1/status.json) | Which model run each file came from, and whether the last build worked | | every run |

There is no server and no API key: the job runs every three hours, and the files
are static. If a model run is missing or looks wrong, that file keeps its last
good version (its `generatedAt` says how old it is), so a bad run never blanks
the app.

## Format

Every file carries `v` (schema version), `kind`, `generatedAt`, the model `run`,
`attribution`, and one shared time axis: `start` (UTC), `stepSeconds` and
`count`. Each series has `count` values, `null` where the model has none.

- **air**: `cells` on CAMS's 0.4° grid over la isla (`lat`, `lon`), each with
  `aqi` (US EPA, 2024 breakpoints: PM 24-hour means, ozone and CO 8-hour means,
  NO₂ and SO₂ hourly) and `pm25`, `pm10`, `o3`, `no2`, `dust` in µg/m³. Read the
  cell nearest to a point.
- **marine**: `spots` (`id`, `lat`, `lon`, plus the wet grid cell used), each
  with `waveHeight`, `waveDirection`, `wavePeriod`, and the same three for
  `windWave`, `swell` and `secondarySwell`. Heights in metres, periods in
  seconds, directions in degrees the waves come **from**. A wave train the
  model doesn't resolve is `null`, never 0.

## Sources and credit

- Air quality and dust: contains modified **Copernicus Atmosphere Monitoring
  Service** information (CAMS global forecast). Neither the European Commission
  nor ECMWF is responsible for any use of this information.
- Waves: **NOAA GFS-Wave** (public domain).
- Both read from [Open-Meteo's open data](https://github.com/open-meteo/open-data)
  on AWS, licensed [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
  (data by [Open-Meteo.com](https://open-meteo.com/)). This repo trims it to
  Puerto Rico and derives the AQI.

The published files are offered under CC BY 4.0 with the credits above.

## Run it

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest -q
python -m snapshot.build --out site   # ~2 minutes; writes site/v1/*.json
```

## License

The code reads `.om` files with Open-Meteo's
[`omfiles`](https://github.com/open-meteo/python-omfiles) library, which is
GPL-2.0-only, so this repository's code is GPL-2.0-only too (see `LICENSE`).
The app only downloads the JSON this job produces.
