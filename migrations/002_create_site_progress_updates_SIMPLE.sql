-- Simplified version for quick testing
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS site_progress_updates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id UUID NOT NULL REFERENCES entities(id),
    user_id UUID NOT NULL REFERENCES users(id),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    update_date DATE NOT NULL DEFAULT CURRENT_DATE,
    vapi_call_id TEXT,

    -- Raw content
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

    -- Boolean flags
    is_wet_weather_closure BOOLEAN DEFAULT FALSE,
    has_urgent_issues BOOLEAN DEFAULT FALSE,
    has_safety_concerns BOOLEAN DEFAULT FALSE,
    has_delays BOOLEAN DEFAULT FALSE,
    has_material_issues BOOLEAN DEFAULT FALSE,

    -- AI-generated
    summary_brief TEXT,
    summary_detailed TEXT,
    extracted_action_items JSONB DEFAULT '[]'::jsonb,
    identified_blockers JSONB DEFAULT '[]'::jsonb,
    flagged_concerns JSONB DEFAULT '[]'::jsonb,

    -- Metadata
    processing_status TEXT DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Essential indexes
CREATE INDEX idx_site_progress_site ON site_progress_updates(site_id);
CREATE INDEX idx_site_progress_tenant ON site_progress_updates(tenant_id);
CREATE INDEX idx_site_progress_date ON site_progress_updates(update_date);
