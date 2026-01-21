-- Migration: Add health_score column to transactions table
-- Run this script if you have an existing database

ALTER TABLE transactions ADD COLUMN IF NOT EXISTS health_score INTEGER;

-- Verify the column was added
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name = 'transactions' AND column_name = 'health_score';
