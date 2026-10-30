"""Load activities from a Garmin Connect data export into Postgres.

Usage:
    python load_garmin.py [path/to/*_summarizedActivities.json]

With no path, the export is looked up under data/garmin_data/. Request the
export at https://www.garmin.com/account/datamanagement/exportdata/ and unzip
it there. Safe to re-run: rows are upserted on activity_id.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

DEFAULT_ROOT = Path(__file__).parent / "data" / "garmin_data"

load_dotenv()


def find_export() -> list[Path]:
    if len(sys.argv) > 1:
        return [Path(sys.argv[1])]
    files = sorted(DEFAULT_ROOT.glob("**/*summarizedActivities*.json"))
    if not files:
        sys.exit(f"No *summarizedActivities*.json found under {DEFAULT_ROOT}")
    return files


def scaled(value, divisor):
    return None if value is None else value / divisor


def to_row(a: dict) -> dict:
    # Garmin export units: distance & elevation in cm, durations in ms.
    # startTimeGmt is a real epoch; startTimeLocal is local wall-clock time encoded as if it were UTC.
    return {
        "activity_id": a["activityId"],
        "activity_type": a.get("activityType"),
        "name": a.get("name"),
        "start_time_utc": datetime.fromtimestamp(a["startTimeGmt"] / 1000, timezone.utc),
        "start_time_local": datetime.fromtimestamp(a["startTimeLocal"] / 1000, timezone.utc).replace(tzinfo=None),
        "distance_m": scaled(a.get("distance"), 100),
        "moving_time_s": round(a["movingDuration"] / 1000) if a.get("movingDuration") else None,
        "elapsed_time_s": round(a["elapsedDuration"] / 1000) if a.get("elapsedDuration") else None,
        "elevation_gain_m": scaled(a.get("elevationGain"), 100),
        "average_heartrate": a.get("avgHr"),
        "max_heartrate": a.get("maxHr"),
        "cadence_spm": a.get("avgDoubleCadence"),
        "start_lat": a.get("startLatitude"),
        "start_lng": a.get("startLongitude"),
        "raw": Jsonb(a),
    }


UPSERT_SQL = """
INSERT INTO garmin.activities (
    activity_id, activity_type, name, start_time_utc, start_time_local,
    distance_m, moving_time_s, elapsed_time_s, elevation_gain_m,
    average_heartrate, max_heartrate, cadence_spm, start_lat, start_lng, raw, loaded_at
) VALUES (
    %(activity_id)s, %(activity_type)s, %(name)s, %(start_time_utc)s, %(start_time_local)s,
    %(distance_m)s, %(moving_time_s)s, %(elapsed_time_s)s, %(elevation_gain_m)s,
    %(average_heartrate)s, %(max_heartrate)s, %(cadence_spm)s, %(start_lat)s, %(start_lng)s, %(raw)s, now()
)
ON CONFLICT (activity_id) DO UPDATE SET
    activity_type = EXCLUDED.activity_type,
    name = EXCLUDED.name,
    start_time_utc = EXCLUDED.start_time_utc,
    start_time_local = EXCLUDED.start_time_local,
    distance_m = EXCLUDED.distance_m,
    moving_time_s = EXCLUDED.moving_time_s,
    elapsed_time_s = EXCLUDED.elapsed_time_s,
    elevation_gain_m = EXCLUDED.elevation_gain_m,
    average_heartrate = EXCLUDED.average_heartrate,
    max_heartrate = EXCLUDED.max_heartrate,
    cadence_spm = EXCLUDED.cadence_spm,
    start_lat = EXCLUDED.start_lat,
    start_lng = EXCLUDED.start_lng,
    raw = EXCLUDED.raw,
    loaded_at = now()
"""


def main() -> None:
    activities = []
    for path in find_export():
        with open(path, encoding="utf-8") as f:
            for chunk in json.load(f):
                activities.extend(chunk["summarizedActivitiesExport"])

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for a in activities:
                cur.execute(UPSERT_SQL, to_row(a))
        conn.commit()

    print(f"Loaded {len(activities)} Garmin activities.")


if __name__ == "__main__":
    main()
