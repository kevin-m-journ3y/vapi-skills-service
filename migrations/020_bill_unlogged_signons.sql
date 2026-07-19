-- 020: bill QR sign-ons that never produced a timesheet
--
-- A sign-on with no timesheet is still delivered service: we hosted the QR,
-- identified the worker, recorded attendance and chased them with reminder SMS.
-- It is billed as its own unit, and ONLY when no timesheet exists for that
-- worker/site/day (otherwise the same cycle would be charged twice).
--
-- Defaults to 0.00 = disabled, so no existing tenant's invoice changes until a
-- rate is set deliberately per tenant.

ALTER TABLE tenant_billing_config
    ADD COLUMN IF NOT EXISTS cost_per_signon_no_timesheet NUMERIC NOT NULL DEFAULT 0.00;

COMMENT ON COLUMN tenant_billing_config.cost_per_signon_no_timesheet IS
    'Rate for a QR sign-on with no matching timesheet (worker/site/day). 0 = not billed.';
