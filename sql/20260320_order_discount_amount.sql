ALTER TABLE orders
  ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0 AFTER shipping_fee;

UPDATE orders
SET discount_amount = 0
WHERE discount_amount IS NULL;
