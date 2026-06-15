-- Migration 019: SMS/MMS site updates feature
-- Adds: inbound-messaging toggle + standard-day config, intra-day artifact rate,
-- artifact-based invoice line items, and three new tables
-- (sms_pending_context, message_log, timesheet_media).
-- See docs/SMS_MMS_SITE_UPDATES_DESIGN.md.
--
-- NOTE: applied manually via the Supabase dashboard (no migration runner).

-- ---------------------------------------------------------------------------
-- 1. qr_signon_config: per-tenant inbound-messaging toggle + standard-day defaults
-- ---------------------------------------------------------------------------
ALTER TABLE qr_signon_config
    ADD COLUMN IF NOT EXISTS inbound_messaging_enabled BOOLEAN DEFAULT false;

-- Standard-day defaults used by the "set to standard day" one-click on
-- unfinalized timesheets. Per-site overrides live in entities.metadata
-- (standard_day_start / standard_day_end), same pattern as is_overhead.
ALTER TABLE qr_signon_config
    ADD COLUMN IF NOT EXISTS standard_day_start TIME DEFAULT '07:00';
ALTER TABLE qr_signon_config
    ADD COLUMN IF NOT EXISTS standard_day_end TIME DEFAULT '15:30';

COMMENT ON COLUMN qr_signon_config.inbound_messaging_enabled IS
    'Super-admin gate for inbound SMS/MMS site updates. App ignores inbound when false.';

-- ---------------------------------------------------------------------------
-- 2. tenant_billing_config: intra-day update rate
--    (Existing cost_per_call_* columns are now treated as channel-agnostic
--     per-ARTIFACT rates: a timesheet rate applies whether logged by voice or
--     text. Kept their legacy names to avoid a breaking rename window.)
-- ---------------------------------------------------------------------------
ALTER TABLE tenant_billing_config
    ADD COLUMN IF NOT EXISTS cost_per_intra_day_update NUMERIC(10,2) DEFAULT 0.00;

COMMENT ON COLUMN tenant_billing_config.cost_per_intra_day_update IS
    'Rate per standalone intra-day update. Default 0: intra-day notes/photos roll into the parent timesheet.';

-- ---------------------------------------------------------------------------
-- 3. invoice_line_items: artifact-based billing (channel-agnostic)
--    vapi_call_id is already nullable. Add artifact identity + channel.
-- ---------------------------------------------------------------------------
ALTER TABLE invoice_line_items
    ADD COLUMN IF NOT EXISTS artifact_id UUID;
ALTER TABLE invoice_line_items
    ADD COLUMN IF NOT EXISTS artifact_type TEXT;   -- timesheet | voice_note | site_update | intra_day_update
ALTER TABLE invoice_line_items
    ADD COLUMN IF NOT EXISTS channel TEXT DEFAULT 'voice';  -- voice | sms

-- Dedup key moves from vapi_call_id -> artifact_id (SMS artifacts have no call id).
-- Partial unique: one line item per artifact per invoice (ignores legacy null rows).
CREATE UNIQUE INDEX IF NOT EXISTS uq_line_items_invoice_artifact
    ON invoice_line_items(invoice_id, artifact_id)
    WHERE artifact_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_line_items_artifact ON invoice_line_items(artifact_id);

-- ---------------------------------------------------------------------------
-- 4. sms_pending_context: short-lived multi-turn SMS state (TTL'd)
--    One active conversation per (tenant, from_number).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sms_pending_context (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    from_number TEXT NOT NULL,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    state TEXT NOT NULL,                 -- e.g. 'awaiting_site', 'awaiting_finish_time'
    payload JSONB DEFAULT '{}'::jsonb,   -- in-flight data (candidate sites, signon_id, etc.)
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tenant_id, from_number)
);

CREATE INDEX IF NOT EXISTS idx_sms_pending_tenant ON sms_pending_context(tenant_id);
CREATE INDEX IF NOT EXISTS idx_sms_pending_expires ON sms_pending_context(expires_at);

ALTER TABLE sms_pending_context ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on sms_pending_context"
    ON sms_pending_context FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE sms_pending_context IS 'Short-lived inbound-SMS conversation state (which-site / finish-time), TTL via expires_at';

-- ---------------------------------------------------------------------------
-- 5. message_log: every inbound/outbound message (metering + note source)
--    Inbound text bodies double as the source for the timesheet work_description
--    at finalization (queried by signon_id). twilio_message_sid UNIQUE gives
--    idempotency against Twilio webhook retries.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    signon_id UUID REFERENCES site_signons(id) ON DELETE SET NULL,
    site_id UUID REFERENCES entities(id) ON DELETE SET NULL,  -- stamped once site is resolved
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'mms')),
    category TEXT,                        -- note | photo | finish | site_answer | help | stop | start | other
    from_number TEXT,
    to_number TEXT,
    body TEXT,                            -- full text (inbound = the worker's note)
    num_segments INTEGER,
    num_media INTEGER DEFAULT 0,
    twilio_message_sid TEXT UNIQUE,
    price NUMERIC(10,5),                  -- Twilio price (populated async, may be null)
    price_unit TEXT,
    status TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_message_log_tenant ON message_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_message_log_created ON message_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_message_log_signon ON message_log(signon_id);
-- Site Log: per-site daily timeline query
CREATE INDEX IF NOT EXISTS idx_message_log_site_created ON message_log(site_id, created_at DESC);

ALTER TABLE message_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on message_log"
    ON message_log FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE message_log IS 'Inbound/outbound SMS+MMS audit + cost metering; inbound bodies feed timesheet work_description';

-- ---------------------------------------------------------------------------
-- 6. timesheet_media: MMS photos, anchored to the sign-on (backfilled to timesheet)
--    Media stored in Supabase Storage (new bucket, e.g. mms-photos); media_url
--    is the stored URL. Deleted from Twilio after ingest.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS timesheet_media (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    site_id UUID REFERENCES entities(id) ON DELETE SET NULL,
    signon_id UUID REFERENCES site_signons(id) ON DELETE SET NULL,
    timesheet_id UUID REFERENCES timesheets(id) ON DELETE SET NULL,
    media_url TEXT NOT NULL,             -- Supabase Storage URL
    content_type TEXT,
    caption TEXT,                        -- associated MMS text body, if any
    source TEXT DEFAULT 'sms_mms',
    twilio_media_sid TEXT UNIQUE,        -- idempotency on re-ingest
    twilio_message_sid TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_timesheet_media_tenant ON timesheet_media(tenant_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_media_signon ON timesheet_media(signon_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_media_timesheet ON timesheet_media(timesheet_id);
CREATE INDEX IF NOT EXISTS idx_timesheet_media_site ON timesheet_media(site_id);

ALTER TABLE timesheet_media ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service role full access on timesheet_media"
    ON timesheet_media FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE timesheet_media IS 'Photos sent via MMS, anchored to a sign-on and backfilled to the day timesheet';
