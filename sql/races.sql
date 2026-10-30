-- Official race results (manually maintained in data/race_results.csv).
-- Run as strava_app:  psql -U strava_app -d running -f sql/races.sql

CREATE SCHEMA IF NOT EXISTS races;

CREATE TABLE IF NOT EXISTS races.distances (
    distance     TEXT PRIMARY KEY,
    distance_km  NUMERIC(7,4) NOT NULL,
    sort_order   INT NOT NULL
);
ALTER TABLE races.distances ADD COLUMN IF NOT EXISTS sport TEXT NOT NULL DEFAULT 'Run';

-- Olympic triathlon = 1.5 km swim + 40 km bike + 10 km run
INSERT INTO races.distances (distance, distance_km, sort_order, sport) VALUES
    ('5K',                5.0,     1, 'Run'),
    ('10K',               10.0,    2, 'Run'),
    ('Half Marathon',     21.0975, 3, 'Run'),
    ('Marathon',          42.195,  4, 'Run'),
    ('Olympic Triathlon', 51.5,    5, 'Triathlon')
ON CONFLICT (distance) DO UPDATE SET
    distance_km = EXCLUDED.distance_km,
    sort_order  = EXCLUDED.sort_order,
    sport       = EXCLUDED.sport;

CREATE TABLE IF NOT EXISTS races.race_results (
    race_date       DATE NOT NULL,
    event_name      TEXT NOT NULL,  -- normalized name for year-over-year comparison
    race_name       TEXT NOT NULL,  -- name as listed by the results site
    distance        TEXT NOT NULL REFERENCES races.distances (distance),
    state           TEXT,
    finish_time_s   INT  NOT NULL,
    age_group       TEXT,
    loaded_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (race_date, event_name)
);

-- Race location for the map. coords_source: gps (Strava/Garmin start point),
-- city (approximate city centre) or state (state centre, city unknown).
ALTER TABLE races.race_results ADD COLUMN IF NOT EXISTS city          TEXT;
ALTER TABLE races.race_results ADD COLUMN IF NOT EXISTS latitude      DOUBLE PRECISION;
ALTER TABLE races.race_results ADD COLUMN IF NOT EXISTS longitude     DOUBLE PRECISION;
ALTER TABLE races.race_results ADD COLUMN IF NOT EXISTS coords_source TEXT;

-- Race results with pace, PR flags, and the matching Strava activity (if any).
-- Dropped first because CREATE OR REPLACE can't change existing column types.
DROP VIEW IF EXISTS races.v_race_results;
CREATE VIEW races.v_race_results AS
SELECT
    r.race_date,
    r.event_name,
    r.race_name,
    d.sport,
    r.distance,
    d.sort_order                                          AS distance_sort,
    -- same units/rounding as strava.v_runs
    ROUND(d.distance_km, 2)                               AS distance_km,
    ROUND(d.distance_km / 1.609344, 2)                    AS distance_mi,
    r.state,
    r.city,
    r.latitude,
    r.longitude,
    r.coords_source,
    r.age_group,
    r.finish_time_s,
    ROUND(r.finish_time_s / 60.0, 2)                      AS finish_time_min,
    to_char(make_interval(secs => r.finish_time_s), 'FMHH24:MI:SS') AS finish_time,
    -- pace only makes sense for running races
    CASE WHEN d.sport = 'Run'
         THEN ROUND((r.finish_time_s / 60.0) / d.distance_km, 2) END              AS pace_min_per_km,
    CASE WHEN d.sport = 'Run'
         THEN ROUND((r.finish_time_s / 60.0) / (d.distance_km / 1.609344), 2) END AS pace_min_per_mi,
    -- personal best per distance, as of each race and overall
    r.finish_time_s = MIN(r.finish_time_s) OVER (
        PARTITION BY r.distance ORDER BY r.race_date
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)  AS was_pr_at_time,
    r.finish_time_s = MIN(r.finish_time_s) OVER (PARTITION BY r.distance) AS is_current_pr,
    a.activity_id                                         AS strava_activity_id,
    ROUND(a.distance_m / 1000.0, 2)                       AS strava_distance_km
FROM races.race_results r
JOIN races.distances d USING (distance)
LEFT JOIN LATERAL (
    -- longest run that day is the race
    SELECT activity_id, distance_m
    FROM strava.activities
    WHERE start_date_local::date = r.race_date
      AND sport_type IN ('Run', 'TrailRun', 'VirtualRun')
    ORDER BY distance_m DESC
    LIMIT 1
) a ON true;
