SET @has_recipient_name := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'orders'
    AND COLUMN_NAME = 'recipient_name'
);

SET @has_recipient_address := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'orders'
    AND COLUMN_NAME = 'recipient_address'
);

SET @ddl_name := IF(
  @has_recipient_name = 0,
  'ALTER TABLE orders ADD COLUMN recipient_name VARCHAR(100) NULL AFTER customer_name',
  'SELECT 1'
);
PREPARE stmt_name FROM @ddl_name;
EXECUTE stmt_name;
DEALLOCATE PREPARE stmt_name;

SET @ddl_address := IF(
  @has_recipient_address = 0,
  'ALTER TABLE orders ADD COLUMN recipient_address VARCHAR(255) NULL AFTER recipient_name',
  'SELECT 1'
);
PREPARE stmt_address FROM @ddl_address;
EXECUTE stmt_address;
DEALLOCATE PREPARE stmt_address;

UPDATE orders
SET recipient_name = customer_name
WHERE (recipient_name IS NULL OR recipient_name = '')
  AND customer_name IS NOT NULL;
