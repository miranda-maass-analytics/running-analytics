-- Strava -> Postgres schema.
-- Run once, connected to the `running` database as the strava_app role:
--   psql -U strava_app -d running -f sql/schema.sql

CREATE SCHEMA IF NOT EXISTS strava;

-- Strava may hand back a new refresh token on any refresh, so the latest one
-- lives here rather than in .env.
CREATE TABLE IF NOT EXISTS strava.oauth_tokens (
    athlete_id     BIGINT PRIMARY KEY,
    access_token   TEXT        NOT NULL,
    refresh_token  TEXT        NOT NULL,
    expires_at     TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per activity (all sport types). Common fields are typed columns;
-- the full API payload is kept in `raw` so nothing is lost.
CREATE TABLE IF NOT EXISTS strava.activities (
    activity_id           BIGINT PRIMARY KEY,
    athlete_id            BIGINT      NOT NULL,
    name                  TEXT,
    sport_type            TEXT,
    workout_type          INT,          -- runs: 0 default, 1 race, 2 long run, 3 workout
    start_date            TIMESTAMPTZ NOT NULL,
    start_date_local      TIMESTAMP   NOT NULL,
    timezone              TEXT,
    distance_m            NUMERIC(10,1),
    moving_time_s         INT,
    elapsed_time_s        INT,
    total_elevation_gain_m NUMERIC(8,1),
    elev_high_m           NUMERIC(8,1),
    elev_low_m            NUMERIC(8,1),
    average_speed_mps     NUMERIC(8,3),
    max_speed_mps         NUMERIC(8,3),
    has_heartrate         BOOLEAN,
    average_heartrate     NUMERIC(5,1),
    max_heartrate         NUMERIC(5,1),
    average_cadence       NUMERIC(6,1),  -- Strava reports running cadence per leg; x2 for spm
    kudos_count           INT,
    achievement_count     INT,
    pr_count              INT,
    trainer               BOOLEAN,
    commute               BOOLEAN,
    manual                BOOLEAN,
    gear_id               TEXT,
    start_lat             DOUBLE PRECISION,
    start_lng             DOUBLE PRECISION,
    summary_polyline      TEXT,
    raw                   JSONB       NOT NULL,
    loaded_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS activities_start_date_idx ON strava.activities (start_date);
CREATE INDEX IF NOT EXISTS activities_sport_type_idx ON strava.activities (sport_type);

-- Power BI-friendly view of runs with derived units.
CREATE OR REPLACE VIEW strava.v_runs AS
SELECT
    activity_id,
    name,
    sport_type,
    CASE workout_type
        WHEN 1 THEN 'Race'
        WHEN 2 THEN 'Long Run'
        WHEN 3 THEN 'Workout'
        ELSE 'Easy/Default'
    END                                                   AS run_type,
    start_date_local,
    start_date_local::date                                AS run_date,
    ROUND(distance_m / 1000.0, 2)                         AS distance_km,
    ROUND(distance_m / 1609.344, 2)                       AS distance_mi,
    ROUND(moving_time_s / 60.0, 1)                        AS moving_time_min,
    ROUND(elapsed_time_s / 60.0, 1)                       AS elapsed_time_min,
    -- pace as decimal minutes (format as mm:ss in Power BI)
    ROUND((moving_time_s / 60.0) / NULLIF(distance_m / 1000.0, 0), 2)   AS pace_min_per_km,
    ROUND((moving_time_s / 60.0) / NULLIF(distance_m / 1609.344, 0), 2) AS pace_min_per_mi,
    total_elevation_gain_m,
    ROUND(total_elevation_gain_m * 3.28084, 0)            AS total_elevation_gain_ft,
    average_heartrate,
    max_heartrate,
    ROUND(average_cadence * 2, 0)                         AS cadence_spm,
    kudos_count,
    pr_count,
    trainer                                               AS is_treadmill,
    gear_id,
    start_lat,
    start_lng
FROM strava.activities
WHERE sport_type IN ('Run', 'TrailRun', 'VirtualRun');
