-- Migration 007: Create call quality assessments table
-- Stores VAPI post-call analysis data for call quality monitoring
-- Populated from end-of-call-report webhooks with analysisPlan data

CREATE TABLE IF NOT EXISTS call_quality_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Call identification
    vapi_call_id TEXT NOT NULL UNIQUE,
    tenant_id UUID REFERENCES tenants(id),
    user_id UUID REFERENCES users(id),

    -- Call metadata
    call_type TEXT,                           -- 'timesheet', 'voice_notes', 'site_updates', 'greeter'
    caller_phone TEXT,
    call_duration_seconds NUMERIC,
    call_cost NUMERIC,
    ended_reason TEXT,                        -- 'customer-ended-call', 'assistant-ended-call', etc.
    assistant_name TEXT,                      -- Which VAPI assistant handled the call

    -- VAPI Analysis (from analysisPlan)
    summary TEXT,                             -- AI-generated call summary
    success_evaluation TEXT,                  -- 'true'/'false' from successEvaluationPlan

    -- Structured quality data (from structuredDataPlan)
    task_completed BOOLEAN,
    sites_logged INTEGER,
    repeated_questions BOOLEAN DEFAULT FALSE,
    filler_phrases_used BOOLEAN DEFAULT FALSE,
    user_had_to_repeat BOOLEAN DEFAULT FALSE,
    user_sentiment TEXT,                      -- 'positive', 'neutral', 'frustrated', 'confused'
    naturalness_score INTEGER,               -- 1-5
    flow_steps_skipped TEXT[],               -- Array of skipped step names
    improvement_notes TEXT,

    -- Raw data for deep analysis
    transcript TEXT,
    structured_data JSONB,                   -- Full structured data from VAPI

    -- Timestamps
    call_started_at TIMESTAMPTZ,
    call_ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_cqa_tenant_id ON call_quality_assessments(tenant_id);
CREATE INDEX idx_cqa_call_started ON call_quality_assessments(call_started_at DESC);
CREATE INDEX idx_cqa_call_type ON call_quality_assessments(call_type);
CREATE INDEX idx_cqa_success ON call_quality_assessments(success_evaluation);
CREATE INDEX idx_cqa_naturalness ON call_quality_assessments(naturalness_score);

-- RLS (disabled for service role access from backend)
ALTER TABLE call_quality_assessments ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service role full access on call_quality_assessments"
    ON call_quality_assessments
    FOR ALL
    USING (true)
    WITH CHECK (true);

COMMENT ON TABLE call_quality_assessments IS 'Stores VAPI post-call analysis data for call quality monitoring. Populated from end-of-call-report webhooks.';
