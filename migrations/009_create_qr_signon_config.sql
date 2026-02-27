-- Migration 009: Create qr_signon_config table
-- Per-tenant QR sign-on configuration

CREATE TABLE IF NOT EXISTS qr_signon_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE UNIQUE,

    -- Feature toggle
    is_enabled BOOLEAN DEFAULT false,

    -- Reminder settings
    reminder_enabled BOOLEAN DEFAULT true,
    first_reminder_time TIME DEFAULT '17:30',
    second_reminder_time TIME DEFAULT '19:00',

    -- Contact info
    jill_phone_number TEXT,       -- shown in SMS: "Call Jill on..."
    manager_phone_number TEXT,    -- shown to unregistered users

    -- UX config
    post_signon_message TEXT DEFAULT 'Remember to complete your health and safety sign-in form.',

    -- Twilio config (per-tenant override, falls back to system default)
    twilio_from_number TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
