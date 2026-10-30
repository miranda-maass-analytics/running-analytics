"""Export summarized running data for the portfolio site's charts.

Usage:
    python export_site_data.py path/to/running-data.js

Only monthly and yearly totals are written for runs, so GPS coordinates, run
names, timestamps, and heart rate never reach the public site. Race results are
already public. The output is a script rather than JSON so the page also works
when opened directly from disk.
"""

import json
import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

MONTHLY_SQL = """
SELECT to_char(run_date, 'YYYY-MM')              AS month,
       count(*)                                  AS runs,
       round(coalesce(sum(distance_km), 0), 2)   AS km,
       round(coalesce(sum(distance_mi), 0), 2)   AS mi,
       round(coalesce(sum(moving_time_min), 0), 1) AS minutes
FROM analytics.v_runs
GROUP BY 1
ORDER BY 1
"""

YEARLY_SQL = """
SELECT year,
       max(distance_km) AS longest_km,
       max(distance_mi) AS longest_mi,
       -- runs per weekday, Monday first
       ARRAY[count(*) FILTER (WHERE dow = 1), count(*) FILTER (WHERE dow = 2),
             count(*) FILTER (WHERE dow = 3), count(*) FILTER (WHERE dow = 4),
             count(*) FILTER (WHERE dow = 5), count(*) FILTER (WHERE dow = 6),
             count(*) FILTER (WHERE dow = 7)] AS weekday_runs
FROM (
    SELECT extract(year FROM run_date)::int AS year,
           extract(isodow FROM run_date)::int AS dow,
           distance_km, distance_mi
    FROM analytics.v_runs
) r
GROUP BY year
ORDER BY year
"""

RACES_SQL = """
SELECT race_date, event_name, sport, distance, distance_sort, state, city,
       round(latitude::numeric, 2)  AS latitude,
       round(longitude::numeric, 2) AS longitude,
       finish_time_s, finish_time, pace_min_per_km, pace_min_per_mi,
       was_pr_at_time, is_current_pr
FROM races.v_race_results
ORDER BY race_date
"""


def plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Unexpected type: {type(value)}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])

    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as conn:
        data = {
            "exported": date.today(),
            "monthly": conn.execute(MONTHLY_SQL).fetchall(),
            "yearly": conn.execute(YEARLY_SQL).fetchall(),
            "races": conn.execute(RACES_SQL).fetchall(),
        }

    payload = json.dumps(data, default=plain, separators=(",", ":"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"window.RUNNING_DATA={payload};\n", encoding="utf-8")
    print(f"Wrote {len(data['monthly'])} months and {len(data['races'])} races to {out}")


if __name__ == "__main__":
    main()
