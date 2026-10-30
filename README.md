# Running Analytics

An end-to-end personal data project: Strava and Garmin activity data and official race results are loaded into a PostgreSQL warehouse, modeled in SQL, and reported in Power BI.

## Architecture

```text
Strava API ---------> strava_sync.py --> strava schema --+
Garmin data export -> load_garmin.py --> garmin schema --+--> analytics.v_runs ---+
Race results CSV ---> load_races.py ---> races schema ---+--> races.v_race_results +--> Power BI
```

## Highlights

- **Incremental API ingestion.** `strava_sync.py` loads only activities newer than the latest stored one, with a `--full` option to pick up edits to older activities. It handles paging and waits out Strava's 15-minute rate-limit windows.
- **OAuth token rotation.** Strava can issue a new refresh token on any refresh, so the latest token is stored in the database rather than in a config file.
- **Idempotent loads.** Every loader upserts on a natural or source key, so scripts are safe to re-run. The race loader also removes rows that were deleted from the CSV.
- **Multi-source deduplication.** `analytics.v_runs` combines both sources in one shape. A Garmin run starting within 10 minutes of a Strava activity is treated as a duplicate, and Strava wins.
- **Source quirks handled at the edge.** Loaders convert Garmin's centimeters and milliseconds to SI units and correct Strava's local timestamps, which carry a misleading `Z` suffix.
- **Raw data retained.** Typed columns sit alongside the full source record in a `JSONB` column, so nothing is lost if the model needs a new field later.
- **Race analytics in SQL.** `races.v_race_results` uses window functions to flag personal records, both as of each race and overall, and a lateral join to match each race to its recorded activity.
- **Power BI as code.** The report is saved in the Power BI Project (`.pbip`) format, so the semantic model and report definitions are readable text that can be version-controlled.

## Repository layout

| Path | Purpose |
|---|---|
| `strava_sync.py` | Pulls Strava activities into Postgres |
| `load_garmin.py` | Loads activities from a Garmin Connect export |
| `load_races.py` | Loads race results from `data/race_results.csv` |
| `sql/schema.sql` | Strava tables and the `strava.v_runs` view |
| `sql/garmin.sql` | Garmin table and the combined `analytics.v_runs` view |
| `sql/races.sql` | Race tables and the `races.v_race_results` view |
| `sql/load_races.sql` | `psql`-only alternative to `load_races.py` |
| `powerbi/` | Power BI Project: report and semantic model |

## Running it

Requires Python, PostgreSQL, and Power BI Desktop to open the report. Strava API credentials come from a [Strava API application](https://www.strava.com/settings/api).

```bash
pip install -r requirements.txt
cp .env.example .env    # then fill in your credentials

psql -U strava_app -d running -f sql/schema.sql
psql -U strava_app -d running -f sql/garmin.sql
psql -U strava_app -d running -f sql/races.sql

python strava_sync.py
python load_garmin.py
python load_races.py
```

The scripts expect a `running` database and a `strava_app` role that can create schemas in it. The report connects to that database on `localhost`.

## Privacy

Credentials and the raw Garmin export are excluded through `.gitignore`, along with Power BI's cached copy of the imported data. Activity data is not stored in this repository.
