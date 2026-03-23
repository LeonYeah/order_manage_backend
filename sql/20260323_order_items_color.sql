SET @has_color := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'order_items'
    AND COLUMN_NAME = 'color'
);

SET @ddl := IF(
  @has_color = 0,
  'ALTER TABLE order_items ADD COLUMN color VARCHAR(50) NULL AFTER amount',
  'SELECT 1'
);

PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
