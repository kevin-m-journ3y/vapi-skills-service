-- Add must_change_password flag to admin_users
-- When true, user must change their password on next login
ALTER TABLE admin_users
ADD COLUMN IF NOT EXISTS must_change_password boolean NOT NULL DEFAULT true;

-- Set existing users to false (they already have their passwords set)
UPDATE admin_users SET must_change_password = false;
