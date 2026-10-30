-- psql-only alternative to load_races.py. Run from the project folder:
--   psql -U strava_app -d running -f sql/load_races.sql

BEGIN;

CREATE TEMP TABLE race_csv (
    race_date      DATE,
    event_name     TEXT,
    race_name      TEXT,
    distance       TEXT,
    state          TEXT,
    official_time  TEXT,
    age_group      TEXT,
    city           TEXT,
    latitude       DOUBLE PRECISION,
    longitude      DOUBLE PRECISION,
    coords_source  TEXT
) ON COMMIT DROP;

\copy race_csv FROM 'data/race_results.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

INSERT INTO races.race_results
    (race_date, event_name, race_name, distance, state, finish_time_s, age_group,
     city, latitude, longitude, coords_source, loaded_at)
SELECT
    race_date, event_name, race_name, distance, NULLIF(state, ''),
    -- "MM:SS" would parse as hours:minutes, so pad it to "0:MM:SS" first
    EXTRACT(EPOCH FROM (CASE WHEN official_time ~ '^\d+:\d+$'
                             THEN '0:' || official_time
                             ELSE official_time END)::interval)::int,
    NULLIF(age_group, ''),
    NULLIF(city, ''), latitude, longitude, NULLIF(coords_source, ''),
    now()
FROM race_csv
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
    loaded_at     = now();

-- keep the table in sync with the CSV
DELETE FROM races.race_results r
WHERE NOT EXISTS (
    SELECT 1 FROM race_csv c
    WHERE c.race_date = r.race_date AND c.event_name = r.event_name
);

COMMIT;

SELECT count(*) AS races_loaded FROM races.race_results;
