-- Migration: Add receipts_used column to user_rate_limits table
-- Run this script if you have an existing database

ALTER TABLE user_rate_limits ADD COLUMN IF NOT EXISTS receipts_used INTEGER DEFAULT 0;

-- Verify the column was added
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'user_rate_limits' AND column_name = 'receipts_used';
