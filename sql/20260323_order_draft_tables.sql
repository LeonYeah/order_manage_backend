CREATE TABLE IF NOT EXISTS draft_orders (
  id BIGINT NOT NULL AUTO_INCREMENT,
  customer_name VARCHAR(100) NULL,
  salesperson VARCHAR(100) NULL,
  recipient_name VARCHAR(100) NULL,
  recipient_address VARCHAR(255) NULL,
  clerk_id BIGINT NOT NULL,
  order_clerk VARCHAR(100) NULL,
  order_date DATE NULL,
  shipping_fee DECIMAL(10,2) NOT NULL DEFAULT 0,
  discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  total_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  settlement_status ENUM('未结账','已结账') NOT NULL DEFAULT '未结账',
  payment_method VARCHAR(20) NULL,
  remark VARCHAR(500) NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_draft_orders_clerk_id (clerk_id),
  KEY idx_draft_orders_order_date (order_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS draft_order_items (
  id BIGINT NOT NULL AUTO_INCREMENT,
  draft_order_id BIGINT NOT NULL,
  product_id BIGINT NOT NULL,
  quantity INT NOT NULL DEFAULT 1,
  unit_price DECIMAL(10,2) NOT NULL DEFAULT 0,
  amount DECIMAL(10,2) NOT NULL DEFAULT 0,
  color VARCHAR(50) NULL,
  sample_date DATE NULL,
  remark VARCHAR(500) NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_draft_order_items_draft_order_id (draft_order_id),
  KEY idx_draft_order_items_product_id (product_id),
  CONSTRAINT fk_draft_order_items_draft_order
    FOREIGN KEY (draft_order_id) REFERENCES draft_orders(id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
