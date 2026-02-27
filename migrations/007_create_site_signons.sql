-- Migration 007: Create site_signons table
-- Records each QR sign-on event at a construction site

CREATE TABLE IF NOT EXISTS site_signons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    -- Sign-on data
    signed_on_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    signed_off_at TIMESTAMP WITH TIME ZONE,
    signoff_method TEXT,  -- 'jill_timesheet', 'auto_next_site', 'manual', 'expired'

    -- Timesheet linkage
    timesheet_id UUID REFERENCES timesheets(id),

    -- Status
    status TEXT NOT NULL DEFAULT 'active',  -- 'active', 'signed_off', 'expired'

    -- Audit trail
    short_code TEXT NOT NULL,  -- which QR code was scanned
    ip_address TEXT,
    user_agent TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Performance indexes
CREATE INDEX idx_site_signons_tenant ON site_signons(tenant_id);
CREATE INDEX idx_site_signons_user ON site_signons(user_id);
CREATE INDEX idx_site_signons_site ON site_signons(site_id);
CREATE INDEX idx_site_signons_date ON site_signons(signed_on_at);
CREATE INDEX idx_site_signons_user_date ON site_signons(user_id, signed_on_at);
CREATE INDEX idx_site_signons_active ON site_signons(user_id, status) WHERE status = 'active';
CREATE INDEX idx_site_signons_tenant_date ON site_signons(tenant_id, signed_on_at);
