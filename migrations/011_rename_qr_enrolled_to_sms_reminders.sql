-- Migration 011: Rename qr_signon_enrolled to sms_reminders_enabled
-- The column only controls SMS reminders, not QR sign-on access.
-- Default to true so all users get reminders unless explicitly opted out.

ALTER TABLE users RENAME COLUMN qr_signon_enrolled TO sms_reminders_enabled;
ALTER TABLE users ALTER COLUMN sms_reminders_enabled SET DEFAULT true;

-- Set all existing users to true (opt everyone in)
UPDATE users SET sms_reminders_enabled = true WHERE sms_reminders_enabled = false;
