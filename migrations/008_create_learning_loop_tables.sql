-- Migration 008: Create learning loop tables
-- Stores eval run results and prompt change history for the quality improvement feedback loop

-- =====================================================
-- EVAL RUNS: Stores every eval suite execution
-- =====================================================

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Run metadata
    run_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_by TEXT NOT NULL DEFAULT 'dashboard',   -- 'dashboard' or 'cli'
    status TEXT NOT NULL DEFAULT 'running',            -- 'running', 'completed', 'failed'

    -- Aggregate results
    total_evals INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    pass_rate NUMERIC,

    -- Per-eval detail
    results JSONB,  -- [{name, status, failure_reason, run_id}]

    -- Error info (if status = 'failed')
    error_message TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_eval_runs_timestamp ON eval_runs(run_timestamp DESC);
CREATE INDEX idx_eval_runs_status ON eval_runs(status);

-- RLS
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on eval_runs"
    ON eval_runs
    FOR ALL
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE eval_runs IS 'Stores VAPI eval suite execution results for the learning loop dashboard.';


-- =====================================================
-- PROMPT CHANGES: Records every prompt push to VAPI
-- =====================================================

CREATE TABLE IF NOT EXISTS prompt_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Which assistant was changed
    assistant_key TEXT NOT NULL,       -- e.g. 'JSMB-Jill-timesheet'
    assistant_id TEXT,                 -- VAPI assistant UUID

    -- What changed
    change_summary TEXT NOT NULL,      -- Human-readable description
    change_category TEXT,              -- 'prompt', 'analysis_plan', 'voice', 'model', etc.
    prompt_hash TEXT,                  -- SHA256 of prompt content for diffing

    -- Who/how
    changed_by TEXT DEFAULT 'script',  -- 'script', 'manual', 'dashboard'

    pushed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_prompt_changes_pushed ON prompt_changes(pushed_at DESC);
CREATE INDEX idx_prompt_changes_assistant ON prompt_changes(assistant_key);

-- RLS
ALTER TABLE prompt_changes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on prompt_changes"
    ON prompt_changes
    FOR ALL
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE prompt_changes IS 'Records prompt and config changes pushed to VAPI assistants for the learning loop.';
