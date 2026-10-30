"""Load official race results from data/race_results.csv into Postgres.

Usage:
    python load_races.py

Edit the CSV to add or correct races, then re-run. Rows are upserted on
(race_date, event_name), and races removed from the CSV are deleted.
"""

import csv
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

CSV_PATH = Path(__file__).parent / "data" / "race_results.csv"

load_dotenv()


def to_seconds(t: str) -> int:
    """'1:02:43' or '58:10' -> seconds."""
    parts = [int(p) for p in t.strip().split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def main() -> None:
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    """
                    INSERT INTO races.race_results
                        (race_date, event_name, race_name, distance, state, finish_time_s, age_group,
                         city, latitude, longitude, coords_source, loaded_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (race_date, event_name) DO UPDATE SET
                        race_name     = EXCLUDED.race_name,
                        distance      = EXCLUDED.distance,
                        state         = EXCLUDED.state,
                        finish_time_s = EXCLUDED.finish_time_s,
                        age_group     = EXCLUDED.age_group,
                        city          = EXCLUDED.city,
                        latitude      = EXCLUDED.latitude,
                        longitude     = EXCLUDED.longitude,
                        coords_source = EXCLUDED.coords_source,
                        loaded_at     = now()
                    """,
                    (
                        r["race_date"], r["event_name"], r["race_name"], r["distance"],
                        r["state"] or None, to_seconds(r["official_time"]), r["age_group"] or None,
                        r.get("city") or None, r.get("latitude") or None, r.get("longitude") or None,
                        r.get("coords_source") or None,
                    ),
                )
            # Keep the table in sync with the CSV.
            cur.execute(
                "DELETE FROM races.race_results WHERE (race_date, event_name) NOT IN "
                "(SELECT d::date, e FROM unnest(%s::text[], %s::text[]) AS t(d, e))",
                ([r["race_date"] for r in rows], [r["event_name"] for r in rows]),
            )
        conn.commit()

    print(f"Loaded {len(rows)} race results.")


if __name__ == "__main__":
    main()
