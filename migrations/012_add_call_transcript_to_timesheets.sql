-- Migration 012: Add call_transcript column to timesheets
-- Stores the full Jill conversation transcript for each timesheet entry

ALTER TABLE timesheets ADD COLUMN IF NOT EXISTS call_transcript text;
