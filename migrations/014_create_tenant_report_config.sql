-- Migration 014: Tenant report configuration
-- Controls which reports are available per tenant

CREATE TABLE IF NOT EXISTS tenant_report_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    report_type TEXT NOT NULL,  -- 'payroll_weekly', 'site_weekly', 'site_progress'
    is_enabled BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, report_type)
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_tenant_report_config_tenant
    ON tenant_report_config(tenant_id) WHERE is_enabled = true;

-- Backfill: Enable all reports for Built By MK (production tenant)
-- Get BBMK tenant ID and insert config rows
DO $$
DECLARE
    bbmk_id UUID;
    report TEXT;
BEGIN
    SELECT id INTO bbmk_id FROM tenants WHERE name ILIKE '%built by mk%' OR name ILIKE '%built by m%' LIMIT 1;

    IF bbmk_id IS NOT NULL THEN
        FOREACH report IN ARRAY ARRAY['payroll_weekly', 'site_weekly', 'site_progress']
        LOOP
            INSERT INTO tenant_report_config (tenant_id, report_type, is_enabled)
            VALUES (bbmk_id, report, true)
            ON CONFLICT (tenant_id, report_type) DO NOTHING;
        END LOOP;
        RAISE NOTICE 'Enabled all reports for Built By MK (%)' , bbmk_id;
    ELSE
        RAISE NOTICE 'Built By MK tenant not found - no backfill performed';
    END IF;
END $$;
