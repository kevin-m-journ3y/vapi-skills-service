-- Migration 010: Add qr_signon_enrolled column to users table
-- Controls which users receive SMS reminders for QR sign-on

ALTER TABLE users ADD COLUMN IF NOT EXISTS qr_signon_enrolled BOOLEAN DEFAULT false;
