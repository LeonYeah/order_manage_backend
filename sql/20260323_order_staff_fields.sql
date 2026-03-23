SET @has_order_clerk := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'orders'
    AND COLUMN_NAME = 'order_clerk'
);

SET @has_salesperson := (
  SELECT COUNT(*)
  FROM information_schema.COLUMNS
  WHERE TABLE_SCHEMA = DATABASE()
    AND TABLE_NAME = 'orders'
    AND COLUMN_NAME = 'salesperson'
);

SET @ddl_order_clerk := IF(
  @has_order_clerk = 0,
  'ALTER TABLE orders ADD COLUMN order_clerk VARCHAR(100) NULL AFTER clerk_id',
  'SELECT 1'
);
PREPARE stmt_order_clerk FROM @ddl_order_clerk;
EXECUTE stmt_order_clerk;
DEALLOCATE PREPARE stmt_order_clerk;

SET @ddl_salesperson := IF(
  @has_salesperson = 0,
  'ALTER TABLE orders ADD COLUMN salesperson VARCHAR(100) NULL AFTER order_clerk',
  'SELECT 1'
);
PREPARE stmt_salesperson FROM @ddl_salesperson;
EXECUTE stmt_salesperson;
DEALLOCATE PREPARE stmt_salesperson;

UPDATE orders o
LEFT JOIN users u ON u.id = o.clerk_id
SET o.order_clerk = IFNULL(u.username, o.order_clerk)
WHERE o.order_clerk IS NULL OR o.order_clerk = '';

UPDATE orders
SET salesperson = NULL
WHERE salesperson IS NOT NULL;
