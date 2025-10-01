-- Enable RLS and add policies for site_progress_updates table
-- Run this after creating the table

-- Enable Row Level Security
ALTER TABLE site_progress_updates ENABLE ROW LEVEL SECURITY;

-- Policy: Users can view updates from their tenant
CREATE POLICY "Users can view their tenant's site updates"
    ON site_progress_updates
    FOR SELECT
    USING (tenant_id IN (
        SELECT tenant_id FROM users WHERE id = auth.uid()
    ));

-- Policy: Users can create updates for their tenant
CREATE POLICY "Users can create site updates for their tenant"
    ON site_progress_updates
    FOR INSERT
    WITH CHECK (
        tenant_id IN (SELECT tenant_id FROM users WHERE id = auth.uid())
        AND user_id = auth.uid()
    );

-- Policy: Users can update their own updates
CREATE POLICY "Users can update their own site updates"
    ON site_progress_updates
    FOR UPDATE
    USING (user_id = auth.uid());

-- Policy: Service role can do anything (for our API)
CREATE POLICY "Service role full access"
    ON site_progress_updates
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- Function to auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_site_progress_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to call the function
CREATE TRIGGER update_site_progress_updates_updated_at
    BEFORE UPDATE ON site_progress_updates
    FOR EACH ROW
    EXECUTE FUNCTION update_site_progress_updated_at();
