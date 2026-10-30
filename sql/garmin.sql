-- Garmin Connect export + combined Strava/Garmin runs view.
-- Run as strava_app:  psql -U strava_app -d running -f sql/garmin.sql

CREATE SCHEMA IF NOT EXISTS garmin;

-- One row per activity from Garmin's summarizedActivities export (all sports),
-- converted to SI units. The original record is kept in `raw`.
CREATE TABLE IF NOT EXISTS garmin.activities (
    activity_id        BIGINT PRIMARY KEY,
    activity_type      TEXT,
    name               TEXT,
    start_time_utc     TIMESTAMPTZ NOT NULL,
    start_time_local   TIMESTAMP   NOT NULL,
    distance_m         NUMERIC(10,1),
    moving_time_s      INT,
    elapsed_time_s     INT,
    elevation_gain_m   NUMERIC(8,1),
    average_heartrate  NUMERIC(5,1),
    max_heartrate      NUMERIC(5,1),
    cadence_spm        NUMERIC(6,1),
    start_lat          DOUBLE PRECISION,
    start_lng          DOUBLE PRECISION,
    raw                JSONB NOT NULL,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS garmin_activities_start_idx ON garmin.activities (start_time_utc);

CREATE SCHEMA IF NOT EXISTS analytics;

-- All runs from both sources, in the shape of strava.v_runs plus `source`.
-- A Garmin run that starts within 10 minutes of a Strava activity is treated as a
-- duplicate and dropped, so Strava wins when a run was synced to both.
CREATE OR REPLACE VIEW analytics.v_runs AS
SELECT r.*, 'Strava'::text AS source
FROM strava.v_runs r

UNION ALL

SELECT
    g.activity_id,
    g.name,
    'Run'                                                   AS sport_type,
    'Easy/Default'                                          AS run_type,
    g.start_time_local                                      AS start_date_local,
    g.start_time_local::date                                AS run_date,
    ROUND(g.distance_m / 1000.0, 2)                         AS distance_km,
    ROUND(g.distance_m / 1609.344, 2)                       AS distance_mi,
    ROUND(g.moving_time_s / 60.0, 1)                        AS moving_time_min,
    ROUND(g.elapsed_time_s / 60.0, 1)                       AS elapsed_time_min,
    ROUND((g.moving_time_s / 60.0) / NULLIF(g.distance_m / 1000.0, 0), 2)   AS pace_min_per_km,
    ROUND((g.moving_time_s / 60.0) / NULLIF(g.distance_m / 1609.344, 0), 2) AS pace_min_per_mi,
    g.elevation_gain_m                                      AS total_elevation_gain_m,
    ROUND(g.elevation_gain_m * 3.28084, 0)                  AS total_elevation_gain_ft,
    g.average_heartrate,
    g.max_heartrate,
    ROUND(g.cadence_spm, 0)                                 AS cadence_spm,
    NULL::int                                               AS kudos_count,
    NULL::int                                               AS pr_count,
    g.activity_type = 'treadmill_running'                   AS is_treadmill,
    NULL::text                                              AS gear_id,
    g.start_lat,
    g.start_lng,
    'Garmin'::text                                          AS source
FROM garmin.activities g
WHERE g.activity_type IN ('running', 'treadmill_running', 'trail_running')
  AND g.distance_m > 0
  AND NOT EXISTS (
      SELECT 1 FROM strava.activities s
      WHERE abs(extract(epoch FROM s.start_date - g.start_time_utc)) < 600
  );
