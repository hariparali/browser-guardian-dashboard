-- ============================================================
-- Browser Guardian — Supabase Schema
-- Run this once in your Supabase project's SQL Editor
-- ============================================================

CREATE TABLE IF NOT EXISTS browsing_history (
    id          BIGSERIAL PRIMARY KEY,
    url         TEXT          NOT NULL,
    title       TEXT,
    domain      TEXT,
    visited_at  TIMESTAMPTZ   NOT NULL,
    -- Classification (done by desktop app before upload)
    is_flagged  BOOLEAN       DEFAULT FALSE,
    category    TEXT          DEFAULT 'unclassified',
    reason      TEXT          DEFAULT '',
    severity    TEXT          DEFAULT 'low',
    created_at  TIMESTAMPTZ   DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bh_visited  ON browsing_history (visited_at DESC);
CREATE INDEX IF NOT EXISTS idx_bh_domain   ON browsing_history (domain);
CREATE INDEX IF NOT EXISTS idx_bh_flagged  ON browsing_history (is_flagged);

-- Row Level Security — allow anonymous reads and inserts (anon key is safe for this)
ALTER TABLE browsing_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all access" ON browsing_history
    FOR ALL
    USING (true)
    WITH CHECK (true);
