CREATE TABLE IF NOT EXISTS request_log (
    request_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country TEXT,
    client_ip INET,
    gender TEXT,
    age_group TEXT,
    income_group TEXT,
    is_banned BOOLEAN NOT NULL,
    client_time TIMESTAMP WITHOUT TIME ZONE,
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    requested_file TEXT NOT NULL,
    status_code SMALLINT NOT NULL
        CHECK (status_code BETWEEN 100 AND 599),
    run_id TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS request_errors (
    request_id BIGINT PRIMARY KEY
        REFERENCES request_log(request_id),
    received_at TIMESTAMP WITH TIME ZONE NOT NULL,
    requested_file TEXT NOT NULL,
    error_code SMALLINT NOT NULL
        CHECK (error_code BETWEEN 100 AND 599 AND error_code <> 200)
);