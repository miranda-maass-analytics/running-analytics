"""Pull Strava activities into Postgres.

Usage:
    python strava_sync.py          # incremental: only activities newer than the latest one stored
    python strava_sync.py --full   # re-pull everything (picks up edits to old activities)
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import psycopg
import requests
from dotenv import load_dotenv
from psycopg.types.json import Jsonb

API_BASE = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
PAGE_SIZE = 200  # Strava's max per page

load_dotenv()

CLIENT_ID = os.environ["STRAVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["STRAVA_CLIENT_SECRET"]
DATABASE_URL = os.environ["DATABASE_URL"]
# Only used to bootstrap the first run; after that the token in the DB wins.
BOOTSTRAP_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")


# ---------------------------------------------------------------- tokens

def refresh_tokens(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def save_tokens(conn, athlete_id: int, tokens: dict) -> None:
    conn.execute(
        """
        INSERT INTO strava.oauth_tokens (athlete_id, access_token, refresh_token, expires_at, updated_at)
        VALUES (%s, %s, %s, to_timestamp(%s), now())
        ON CONFLICT (athlete_id) DO UPDATE SET
            access_token  = EXCLUDED.access_token,
            refresh_token = EXCLUDED.refresh_token,
            expires_at    = EXCLUDED.expires_at,
            updated_at    = now()
        """,
        (athlete_id, tokens["access_token"], tokens["refresh_token"], tokens["expires_at"]),
    )
    conn.commit()


def get_access_token(conn) -> tuple[str, int]:
    """Return a valid (access_token, athlete_id), refreshing if needed."""
    row = conn.execute(
        "SELECT athlete_id, access_token, refresh_token, expires_at "
        "FROM strava.oauth_tokens ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()

    if row:
        athlete_id, access_token, refresh_token, expires_at = row
        # Refresh a few minutes early so the token can't expire mid-run.
        if expires_at.timestamp() - time.time() > 300:
            return access_token, athlete_id
    else:
        if not BOOTSTRAP_REFRESH_TOKEN:
            sys.exit("No token in the database and STRAVA_REFRESH_TOKEN is not set in .env.")
        refresh_token = BOOTSTRAP_REFRESH_TOKEN
        athlete_id = None

    tokens = refresh_tokens(refresh_token)
    if athlete_id is None:
        athlete = requests.get(
            f"{API_BASE}/athlete",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=30,
        )
        athlete.raise_for_status()
        athlete_id = athlete.json()["id"]

    save_tokens(conn, athlete_id, tokens)
    print("Access token refreshed.")
    return tokens["access_token"], athlete_id


# ---------------------------------------------------------------- API

def api_get(path: str, token: str, params: dict) -> list:
    while True:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=30,
        )
        if resp.status_code == 429:
            # Rate limits reset on 15-minute boundaries.
            wait = 900 - (int(time.time()) % 900) + 5
            print(f"Rate limited; sleeping {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code == 401:
            sys.exit(
                f"401 Unauthorized from Strava: {resp.text}\n"
                "The token probably lacks the activity:read_all scope. Re-authorize with that scope, "
                "put the new refresh token in .env, and run: DELETE FROM strava.oauth_tokens;"
            )
        resp.raise_for_status()
        return resp.json()


def fetch_activities(token: str, after_epoch: int | None):
    page = 1
    while True:
        params = {"per_page": PAGE_SIZE, "page": page}
        if after_epoch:
            params["after"] = after_epoch
        batch = api_get("/athlete/activities", token, params)
        if not batch:
            return
        yield from batch
        page += 1


# ---------------------------------------------------------------- load

UPSERT_SQL = """
INSERT INTO strava.activities (
    activity_id, athlete_id, name, sport_type, workout_type,
    start_date, start_date_local, timezone,
    distance_m, moving_time_s, elapsed_time_s,
    total_elevation_gain_m, elev_high_m, elev_low_m,
    average_speed_mps, max_speed_mps,
    has_heartrate, average_heartrate, max_heartrate, average_cadence,
    kudos_count, achievement_count, pr_count,
    trainer, commute, manual, gear_id,
    start_lat, start_lng, summary_polyline, raw, loaded_at
) VALUES (
    %(activity_id)s, %(athlete_id)s, %(name)s, %(sport_type)s, %(workout_type)s,
    %(start_date)s, %(start_date_local)s, %(timezone)s,
    %(distance_m)s, %(moving_time_s)s, %(elapsed_time_s)s,
    %(total_elevation_gain_m)s, %(elev_high_m)s, %(elev_low_m)s,
    %(average_speed_mps)s, %(max_speed_mps)s,
    %(has_heartrate)s, %(average_heartrate)s, %(max_heartrate)s, %(average_cadence)s,
    %(kudos_count)s, %(achievement_count)s, %(pr_count)s,
    %(trainer)s, %(commute)s, %(manual)s, %(gear_id)s,
    %(start_lat)s, %(start_lng)s, %(summary_polyline)s, %(raw)s, now()
)
ON CONFLICT (activity_id) DO UPDATE SET
    name = EXCLUDED.name,
    sport_type = EXCLUDED.sport_type,
    workout_type = EXCLUDED.workout_type,
    start_date = EXCLUDED.start_date,
    start_date_local = EXCLUDED.start_date_local,
    timezone = EXCLUDED.timezone,
    distance_m = EXCLUDED.distance_m,
    moving_time_s = EXCLUDED.moving_time_s,
    elapsed_time_s = EXCLUDED.elapsed_time_s,
    total_elevation_gain_m = EXCLUDED.total_elevation_gain_m,
    elev_high_m = EXCLUDED.elev_high_m,
    elev_low_m = EXCLUDED.elev_low_m,
    average_speed_mps = EXCLUDED.average_speed_mps,
    max_speed_mps = EXCLUDED.max_speed_mps,
    has_heartrate = EXCLUDED.has_heartrate,
    average_heartrate = EXCLUDED.average_heartrate,
    max_heartrate = EXCLUDED.max_heartrate,
    average_cadence = EXCLUDED.average_cadence,
    kudos_count = EXCLUDED.kudos_count,
    achievement_count = EXCLUDED.achievement_count,
    pr_count = EXCLUDED.pr_count,
    trainer = EXCLUDED.trainer,
    commute = EXCLUDED.commute,
    manual = EXCLUDED.manual,
    gear_id = EXCLUDED.gear_id,
    start_lat = EXCLUDED.start_lat,
    start_lng = EXCLUDED.start_lng,
    summary_polyline = EXCLUDED.summary_polyline,
    raw = EXCLUDED.raw,
    loaded_at = now()
"""


def to_row(a: dict, athlete_id: int) -> dict:
    latlng = a.get("start_latlng") or [None, None]
    return {
        "activity_id": a["id"],
        "athlete_id": athlete_id,
        "name": a.get("name"),
        "sport_type": a.get("sport_type") or a.get("type"),
        "workout_type": a.get("workout_type"),
        "start_date": a["start_date"],
        # Strava suffixes local time with "Z" even though it isn't UTC; drop it.
        "start_date_local": a["start_date_local"].rstrip("Z"),
        "timezone": a.get("timezone"),
        "distance_m": a.get("distance"),
        "moving_time_s": a.get("moving_time"),
        "elapsed_time_s": a.get("elapsed_time"),
        "total_elevation_gain_m": a.get("total_elevation_gain"),
        "elev_high_m": a.get("elev_high"),
        "elev_low_m": a.get("elev_low"),
        "average_speed_mps": a.get("average_speed"),
        "max_speed_mps": a.get("max_speed"),
        "has_heartrate": a.get("has_heartrate"),
        "average_heartrate": a.get("average_heartrate"),
        "max_heartrate": a.get("max_heartrate"),
        "average_cadence": a.get("average_cadence"),
        "kudos_count": a.get("kudos_count"),
        "achievement_count": a.get("achievement_count"),
        "pr_count": a.get("pr_count"),
        "trainer": a.get("trainer"),
        "commute": a.get("commute"),
        "manual": a.get("manual"),
        "gear_id": a.get("gear_id"),
        "start_lat": latlng[0],
        "start_lng": latlng[1],
        "summary_polyline": (a.get("map") or {}).get("summary_polyline"),
        "raw": Jsonb(a),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="re-pull all activities")
    args = parser.parse_args()

    with psycopg.connect(DATABASE_URL) as conn:
        token, athlete_id = get_access_token(conn)

        after_epoch = None
        if not args.full:
            latest = conn.execute(
                "SELECT max(start_date) FROM strava.activities WHERE athlete_id = %s",
                (athlete_id,),
            ).fetchone()[0]
            if latest:
                after_epoch = int(latest.timestamp())
                print(f"Incremental sync: activities after {latest:%Y-%m-%d %H:%M} UTC")

        count = 0
        with conn.cursor() as cur:
            for activity in fetch_activities(token, after_epoch):
                cur.execute(UPSERT_SQL, to_row(activity, athlete_id))
                count += 1
                if count % PAGE_SIZE == 0:
                    conn.commit()
                    print(f"  {count} activities loaded...")
        conn.commit()

    print(f"Done. {count} activities upserted at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.")


if __name__ == "__main__":
    main()
