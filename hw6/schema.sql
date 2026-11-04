BEGIN;

CREATE SCHEMA hw6;

CREATE TEMP TABLE migration_source AS
SELECT *
FROM public.request_log
WHERE client_ip IS NOT NULL
  AND country IS NOT NULL
  AND client_ip <> '203.0.113.10'::inet;

CREATE TABLE hw6.countries (
    country TEXT PRIMARY KEY,
    is_banned BOOLEAN NOT NULL
);

CREATE TABLE hw6.clients (
    client_ip INET PRIMARY KEY,
    country TEXT NOT NULL REFERENCES hw6.countries(country)
);

CREATE TABLE hw6.requests (
    request_id BIGINT PRIMARY KEY,
    client_ip INET NOT NULL REFERENCES hw6.clients(client_ip),
    gender TEXT,
    age_group TEXT,
    income_group TEXT,
    client_time TIMESTAMP WITHOUT TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    requested_file TEXT NOT NULL,
    status_code SMALLINT NOT NULL
        CHECK (status_code BETWEEN 100 AND 599),
    run_id TEXT NOT NULL
);

INSERT INTO hw6.countries (country, is_banned)
SELECT DISTINCT country, is_banned
FROM migration_source;

INSERT INTO hw6.clients (client_ip, country)
SELECT DISTINCT client_ip, country
FROM migration_source;

INSERT INTO hw6.requests (
    request_id,
    client_ip,
    gender,
    age_group,
    income_group,
    client_time,
    received_at,
    requested_file,
    status_code,
    run_id
)
SELECT
    request_id,
    client_ip,
    gender,
    age_group,
    income_group,
    client_time,
    received_at,
    requested_file,
    status_code,
    run_id
FROM migration_source;

-- Error details are already stored in requests.
CREATE VIEW hw6.request_errors AS
SELECT
    request_id,
    received_at,
    requested_file,
    status_code AS error_code
FROM hw6.requests
WHERE status_code <> 200;

DROP TABLE migration_source;

COMMIT;