-- Migration 017: Create billing & invoicing tables
-- Supports per-tenant billing config, invoice generation, and itemised call detail

-- Table 1: Per-tenant billing configuration
CREATE TABLE IF NOT EXISTS tenant_billing_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,
    platform_fee NUMERIC(10,2) DEFAULT 500.00,
    platform_discount_percent NUMERIC(5,2) DEFAULT 0,
    cost_per_call_timesheet NUMERIC(10,2) DEFAULT 1.00,
    cost_per_call_voice_notes NUMERIC(10,2) DEFAULT 1.00,
    cost_per_call_site_updates NUMERIC(10,2) DEFAULT 2.00,
    billing_start_date DATE,
    invoice_prefix TEXT DEFAULT 'INV',
    usd_to_aud_rate NUMERIC(6,4) DEFAULT 1.5500,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_billing_config_tenant ON tenant_billing_config(tenant_id);

ALTER TABLE tenant_billing_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on tenant_billing_config"
    ON tenant_billing_config FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE tenant_billing_config IS 'Per-tenant billing settings: platform fee, per-skill call costs, FX rate, invoice prefix';

-- Table 2: Generated invoices
CREATE TABLE IF NOT EXISTS invoices (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    invoice_number TEXT NOT NULL UNIQUE,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    total_calls INTEGER DEFAULT 0,
    total_call_cost NUMERIC(10,2) DEFAULT 0,
    platform_fee NUMERIC(10,2) DEFAULT 0,
    platform_discount_percent NUMERIC(5,2) DEFAULT 0,
    platform_fee_after_discount NUMERIC(10,2) DEFAULT 0,
    total_amount NUMERIC(10,2) DEFAULT 0,
    total_actual_cost_aud NUMERIC(10,2) DEFAULT 0,
    usd_to_aud_rate NUMERIC(6,4) DEFAULT 1.5500,
    status TEXT DEFAULT 'draft' CHECK (status IN ('draft', 'sent', 'paid')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_invoices_tenant ON invoices(tenant_id);
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_created ON invoices(created_at DESC);

ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on invoices"
    ON invoices FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE invoices IS 'Generated billing invoices with snapshot of rates at generation time';

-- Table 3: Invoice line items (one per billable call)
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    call_date TIMESTAMPTZ NOT NULL,
    user_name TEXT,
    call_type TEXT,
    site_name TEXT,
    duration_seconds INTEGER,
    unit_cost NUMERIC(10,2),
    actual_cost_usd NUMERIC(10,4),
    actual_cost_aud NUMERIC(10,4),
    vapi_call_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_line_items_invoice ON invoice_line_items(invoice_id);
CREATE INDEX idx_line_items_call_date ON invoice_line_items(call_date);

ALTER TABLE invoice_line_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on invoice_line_items"
    ON invoice_line_items FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE invoice_line_items IS 'Itemised call detail for each invoice, like a phone bill';
