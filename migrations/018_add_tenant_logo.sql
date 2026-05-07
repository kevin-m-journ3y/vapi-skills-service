-- Migration 018: Add logo_url to tenants for per-tenant PDF branding

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS logo_url text;
