-- Backfill unit_price for existing transactions where it's NULL
-- unit_price = item_price / quantity

UPDATE transactions
SET unit_price = CASE
    WHEN quantity > 0 THEN item_price / quantity
    ELSE item_price
END
WHERE unit_price IS NULL;
