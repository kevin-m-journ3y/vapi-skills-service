-- Migration: Create site_progress_updates table
-- Description: Stores structured site progress updates with AI-processed insights

CREATE TABLE IF NOT EXISTS site_progress_updates (
    -- Identity
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    update_date DATE NOT NULL DEFAULT CURRENT_DATE,
    vapi_call_id TEXT,

    -- Raw Content (text fields from conversation)
    main_focus TEXT,
    materials_delivered TEXT,
    work_progress TEXT,
    issues TEXT,
    delays TEXT,
    staffing TEXT,
    site_visitors TEXT,
    site_conditions TEXT,
    follow_up_actions TEXT,
    raw_transcript TEXT,

    -- Boolean Flags (for easy querying)
    is_wet_weather_closure BOOLEAN DEFAULT FALSE,
    has_urgent_issues BOOLEAN DEFAULT FALSE,
    has_safety_concerns BOOLEAN DEFAULT FALSE,
    has_delays BOOLEAN DEFAULT FALSE,
    has_material_issues BOOLEAN DEFAULT FALSE,

    -- AI-Generated Content (OpenAI processed)
    summary_brief TEXT,
    summary_detailed TEXT,
    extracted_action_items JSONB DEFAULT '[]'::jsonb,
    identified_blockers JSONB DEFAULT '[]'::jsonb,
    flagged_concerns JSONB DEFAULT '[]'::jsonb,

    -- Metadata
    processing_status TEXT DEFAULT 'pending' CHECK (processing_status IN ('pending', 'processing', 'completed', 'failed')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_site_id ON site_progress_updates(site_id);
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_tenant_id ON site_progress_updates(tenant_id);
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_user_id ON site_progress_updates(user_id);
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_update_date ON site_progress_updates(update_date);
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_vapi_call_id ON site_progress_updates(vapi_call_id);
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_urgent ON site_progress_updates(has_urgent_issues) WHERE has_urgent_issues = TRUE;
CREATE INDEX IF NOT EXISTS idx_site_progress_updates_safety ON site_progress_updates(has_safety_concerns) WHERE has_safety_concerns = TRUE;

-- Enable Row Level Security
ALTER TABLE site_progress_updates ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only see updates from their tenant
CREATE POLICY "Users can view their tenant's site updates"
    ON site_progress_updates
    FOR SELECT
    USING (tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid()));

-- RLS Policy: Users can insert updates for their tenant
CREATE POLICY "Users can create site updates for their tenant"
    ON site_progress_updates
    FOR INSERT
    WITH CHECK (
        tenant_id = (SELECT tenant_id FROM users WHERE id = auth.uid())
        AND user_id = auth.uid()
    );

-- RLS Policy: Users can update their own updates
CREATE POLICY "Users can update their own site updates"
    ON site_progress_updates
    FOR UPDATE
    USING (user_id = auth.uid());

-- Function to automatically update updated_at timestamp
CREATE OR REPLACE FUNCTION update_site_progress_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call the function
CREATE TRIGGER update_site_progress_updates_updated_at
    BEFORE UPDATE ON site_progress_updates
    FOR EACH ROW
    EXECUTE FUNCTION update_site_progress_updated_at();

-- Comments for documentation
COMMENT ON TABLE site_progress_updates IS 'Stores daily site progress updates with AI-processed insights and action items';
COMMENT ON COLUMN site_progress_updates.extracted_action_items IS 'JSON array of action items: [{action, priority, deadline, assigned_to}]';
COMMENT ON COLUMN site_progress_updates.identified_blockers IS 'JSON array of blockers: [{blocker_type, description, impact, estimated_resolution}]';
COMMENT ON COLUMN site_progress_updates.flagged_concerns IS 'JSON array of concerns: [{concern_type, severity, description}]';
