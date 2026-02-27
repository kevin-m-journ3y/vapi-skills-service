-- Migration 006: Create tenant_skills table for tenant-level skill isolation
-- Applied: 2026-02-27

CREATE TABLE IF NOT EXISTS tenant_skills (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    skill_id UUID NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
    is_enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(tenant_id, skill_id)
);

CREATE INDEX idx_tenant_skills_tenant ON tenant_skills(tenant_id) WHERE is_enabled = true;

-- Backfill: enable all existing skills for all existing tenants
INSERT INTO tenant_skills (tenant_id, skill_id, is_enabled)
SELECT t.id, s.id, true
FROM tenants t CROSS JOIN skills s
ON CONFLICT (tenant_id, skill_id) DO NOTHING;
