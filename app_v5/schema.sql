-- v5.0 local-only SQLite foundation. No credentials or public evidence exports.
CREATE TABLE IF NOT EXISTS search_profiles (
    profile_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    keyword TEXT NOT NULL,
    region_id TEXT NOT NULL,
    max_price_krw INTEGER CHECK (max_price_krw IS NULL OR max_price_krw >= 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_jobs (
    job_id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES search_profiles(profile_id),
    status TEXT NOT NULL CHECK (status IN ('PENDING','RUNNING','COMPLETED','FAILED')),
    created_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    CHECK ((status IN ('COMPLETED','FAILED')) = (finished_at_utc IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS listings (
    listing_key TEXT PRIMARY KEY CHECK(length(listing_key) = 64),
    platform TEXT NOT NULL DEFAULT 'daangn' CHECK(platform = 'daangn'),
    canonical_url TEXT NOT NULL,
    first_seen_utc TEXT NOT NULL,
    last_seen_utc TEXT NOT NULL,
    latest_observation_id INTEGER
);

CREATE TABLE IF NOT EXISTS listing_observations (
    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_key TEXT NOT NULL REFERENCES listings(listing_key),
    job_id TEXT NOT NULL REFERENCES collection_jobs(job_id),
    profile_id TEXT NOT NULL REFERENCES search_profiles(profile_id),
    observed_at_utc TEXT NOT NULL,
    title TEXT,
    price_krw INTEGER CHECK (price_krw IS NULL OR price_krw >= 0),
    price_verified INTEGER NOT NULL CHECK(price_verified IN (0,1)),
    transaction_status TEXT NOT NULL CHECK(transaction_status IN
        ('FOR_SALE','RESERVED','SOLD','NOT_OBSERVABLE','AMBIGUOUS','NOT_VERIFIED')),
    primary_status_verified INTEGER NOT NULL CHECK(primary_status_verified IN (0,1)),
    stock_availability TEXT NOT NULL CHECK(stock_availability IN
        ('IN_STOCK','OUT_OF_STOCK','SOLD_OUT','PRE_ORDER','PRE_SALE',
         'OTHER','NOT_OBSERVABLE','AMBIGUOUS')),
    stock_verified INTEGER NOT NULL CHECK(stock_verified IN (0,1)),
    description_sha256 TEXT,
    description_verified INTEGER NOT NULL CHECK(description_verified IN (0,1)),
    evidence_level TEXT NOT NULL CHECK(evidence_level IN ('REVIEWABLE','ADVISORY')),
    sale_filter_eligible INTEGER NOT NULL CHECK(sale_filter_eligible IN (0,1)),
    sale_state_inferred INTEGER NOT NULL CHECK(sale_state_inferred IN (0,1)),
    payload_sha256 TEXT NOT NULL,
    UNIQUE(job_id, listing_key)
);

CREATE TABLE IF NOT EXISTS listing_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_key TEXT NOT NULL REFERENCES listings(listing_key),
    observation_id INTEGER NOT NULL REFERENCES listing_observations(observation_id),
    event_type TEXT NOT NULL CHECK(event_type IN (
      'PRICE_DROPPED','PRICE_INCREASED','DESCRIPTION_CHANGED',
      'TRANSACTION_STATUS_CHANGED','STOCK_AVAILABILITY_CHANGED')),
    previous_value TEXT NOT NULL,
    current_value TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(observation_id, event_type)
);

CREATE INDEX IF NOT EXISTS idx_observations_listing_time
    ON listing_observations(listing_key, observed_at_utc DESC, observation_id DESC);
CREATE INDEX IF NOT EXISTS idx_observations_profile_time
    ON listing_observations(profile_id, observed_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_events_listing_id
    ON listing_events(listing_key, event_id DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_profile
    ON collection_jobs(profile_id, created_at_utc DESC);

-- v5 schema v2: preserve sealed v4.34 display provenance, not transaction truth.
CREATE TABLE IF NOT EXISTS listing_source_evidence (
    observation_id INTEGER PRIMARY KEY REFERENCES listing_observations(observation_id),
    source_version TEXT NOT NULL CHECK(source_version = '4.34'),
    capture_created_utc TEXT NOT NULL,
    category_display TEXT NOT NULL CHECK(category_display = '디지털기기'),
    sale_display TEXT NOT NULL CHECK(sale_display IN ('판매 가능 추정', '판매중 직접 확인')),
    source_observation_count INTEGER NOT NULL
        CHECK(source_observation_count BETWEEN 1 AND 9),
    primary_h1_captured INTEGER NOT NULL CHECK(primary_h1_captured = 1),
    full_recommendation_approved INTEGER NOT NULL CHECK(full_recommendation_approved = 0)
);

-- Bind a local DB to its owner HMAC key; wrong-key reopening must fail.
CREATE TABLE IF NOT EXISTS history_store_meta (
    name TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- v5 schema v3: bind an authenticated producer claim to one immutable job.
-- No user, seller, listing title, plaintext URL, or secret material here.
CREATE TABLE IF NOT EXISTS capture_attestations (
    job_id TEXT PRIMARY KEY REFERENCES collection_jobs(job_id),
    repository TEXT NOT NULL CHECK(repository = 'mozzibara/auto-daangn'),
    workflow TEXT NOT NULL CHECK(workflow = 'secure-links-v434.yml'),
    source_commit_sha TEXT NOT NULL CHECK(length(source_commit_sha) = 40),
    run_id INTEGER NOT NULL CHECK(run_id > 0),
    run_attempt INTEGER NOT NULL CHECK(run_attempt > 0),
    signer_key_id TEXT NOT NULL CHECK(length(signer_key_id) = 24),
    attestation_sha256 TEXT NOT NULL CHECK(length(attestation_sha256) = 64),
    encrypted_sha256 TEXT NOT NULL CHECK(length(encrypted_sha256) = 64),
    capture_ended_utc TEXT NOT NULL,
    UNIQUE(run_id, run_attempt),
    UNIQUE(attestation_sha256)
);
