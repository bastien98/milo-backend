-- Smart Budget Feature Migration
-- This migration adds support for smart budgets with automatic monthly rollover

-- ============================================================================
-- 1. Add is_smart_budget column to budgets table (if not exists)
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'budgets' AND column_name = 'is_smart_budget'
    ) THEN
        ALTER TABLE budgets ADD COLUMN is_smart_budget BOOLEAN DEFAULT true;
    END IF;
END $$;

-- ============================================================================
-- 2. Create budget_history table (if not exists)
-- ============================================================================
CREATE TABLE IF NOT EXISTS budget_history (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id VARCHAR NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    monthly_amount FLOAT NOT NULL,
    category_allocations JSONB,
    month VARCHAR(7) NOT NULL,
    was_smart_budget BOOLEAN NOT NULL,
    was_deleted BOOLEAN DEFAULT false,
    notifications_enabled BOOLEAN DEFAULT true,
    alert_thresholds JSONB DEFAULT '[0.5, 0.75, 0.9]'::JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(user_id, month)
);

-- Create index for efficient lookups
CREATE INDEX IF NOT EXISTS idx_budget_history_user_month ON budget_history(user_id, month);

-- ============================================================================
-- 3. Backfill history for existing budgets
-- ============================================================================
INSERT INTO budget_history (
    user_id,
    monthly_amount,
    category_allocations,
    month,
    was_smart_budget,
    was_deleted,
    notifications_enabled,
    alert_thresholds,
    created_at
)
SELECT
    user_id,
    monthly_amount,
    category_allocations,
    TO_CHAR(created_at, 'YYYY-MM') as month,
    COALESCE(is_smart_budget, true) as was_smart_budget,
    false as was_deleted,
    notifications_enabled,
    alert_thresholds,
    created_at
FROM budgets
ON CONFLICT (user_id, month) DO NOTHING;

-- ============================================================================
-- 4. Create triggers for automatic budget_history maintenance (OPTIONAL)
-- ============================================================================
-- Note: The API layer already handles history management, so these triggers
-- are optional and provide an additional layer of data consistency.

-- Trigger function: Create/update history entry when budget is created or updated
CREATE OR REPLACE FUNCTION create_budget_history()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO budget_history (
        user_id,
        monthly_amount,
        category_allocations,
        month,
        was_smart_budget,
        was_deleted,
        notifications_enabled,
        alert_thresholds
    ) VALUES (
        NEW.user_id,
        NEW.monthly_amount,
        NEW.category_allocations,
        TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM'),
        COALESCE(NEW.is_smart_budget, true),
        false,
        NEW.notifications_enabled,
        NEW.alert_thresholds
    )
    ON CONFLICT (user_id, month)
    DO UPDATE SET
        monthly_amount = EXCLUDED.monthly_amount,
        category_allocations = EXCLUDED.category_allocations,
        was_smart_budget = EXCLUDED.was_smart_budget,
        notifications_enabled = EXCLUDED.notifications_enabled,
        alert_thresholds = EXCLUDED.alert_thresholds;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger function: Mark as deleted in history when budget is deleted
CREATE OR REPLACE FUNCTION mark_budget_deleted()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE budget_history
    SET was_deleted = true
    WHERE user_id = OLD.user_id
    AND month = TO_CHAR(NOW() AT TIME ZONE 'UTC', 'YYYY-MM');

    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

-- Drop existing triggers if they exist
DROP TRIGGER IF EXISTS budget_created_trigger ON budgets;
DROP TRIGGER IF EXISTS budget_updated_trigger ON budgets;
DROP TRIGGER IF EXISTS budget_deleted_trigger ON budgets;

-- Create triggers
CREATE TRIGGER budget_created_trigger
AFTER INSERT ON budgets
FOR EACH ROW
EXECUTE FUNCTION create_budget_history();

CREATE TRIGGER budget_updated_trigger
AFTER UPDATE ON budgets
FOR EACH ROW
EXECUTE FUNCTION create_budget_history();

CREATE TRIGGER budget_deleted_trigger
BEFORE DELETE ON budgets
FOR EACH ROW
EXECUTE FUNCTION mark_budget_deleted();

-- ============================================================================
-- Verification query (optional - run to verify migration)
-- ============================================================================
-- SELECT
--     'budgets.is_smart_budget' as check_item,
--     CASE WHEN EXISTS (
--         SELECT 1 FROM information_schema.columns
--         WHERE table_name = 'budgets' AND column_name = 'is_smart_budget'
--     ) THEN 'OK' ELSE 'MISSING' END as status
-- UNION ALL
-- SELECT
--     'budget_history table' as check_item,
--     CASE WHEN EXISTS (
--         SELECT 1 FROM information_schema.tables
--         WHERE table_name = 'budget_history'
--     ) THEN 'OK' ELSE 'MISSING' END as status
-- UNION ALL
-- SELECT
--     'budget_history count' as check_item,
--     (SELECT COUNT(*)::TEXT FROM budget_history) as status;
