-- Migration 008: Create site_qr_codes table
-- Static QR codes per site, one QR per site

CREATE TABLE IF NOT EXISTS site_qr_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    short_code TEXT NOT NULL UNIQUE,  -- 8-char URL-safe string for /s/{short_code}
    is_active BOOLEAN DEFAULT true,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_by UUID REFERENCES admin_users(id),

    UNIQUE(site_id)  -- one QR code per site
);

CREATE UNIQUE INDEX idx_site_qr_codes_short_code ON site_qr_codes(short_code);
CREATE INDEX idx_site_qr_codes_site ON site_qr_codes(site_id);
CREATE INDEX idx_site_qr_codes_tenant ON site_qr_codes(tenant_id);
