from db import get_db


def ignore_duplicate_column(exc):
    if not exc.args or exc.args[0] != 1060:
        raise exc


def ensure_order_settlement_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'settlement_status'")
        has_status = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'settlement_remind_until'")
        has_remind_until = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'settlement_at'")
        has_settlement_at = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'discount_amount'")
        has_discount_amount = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'review_status'")
        has_review_status = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reject_reason'")
        has_reject_reason = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'rejected_by'")
        has_rejected_by = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'rejected_at'")
        has_rejected_at = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'resubmitted_at'")
        has_resubmitted_at = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_status'")
        has_reverse_checkout_status = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_reason'")
        has_reverse_checkout_reason = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_requested_by'")
        has_reverse_checkout_requested_by = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_requested_at'")
        has_reverse_checkout_requested_at = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_rejected_by'")
        has_reverse_checkout_rejected_by = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'reverse_checkout_rejected_at'")
        has_reverse_checkout_rejected_at = cursor.fetchone()

        if not has_status:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN settlement_status ENUM('未结账','已结账') NOT NULL DEFAULT '已结账' AFTER payment_method"
            )
        if not has_remind_until:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN settlement_remind_until DATETIME NULL AFTER settlement_status"
            )
        if not has_settlement_at:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN settlement_at DATETIME NULL AFTER settlement_remind_until"
            )
        if not has_discount_amount:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0 AFTER shipping_fee"
            )
        if not has_review_status:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN review_status ENUM('未审核','已驳回','已通过') NOT NULL DEFAULT '已通过' AFTER settlement_at"
            )
        else:
            cursor.execute(
                "ALTER TABLE orders MODIFY COLUMN review_status "
                "ENUM('待审核','未审核','已驳回','已通过') NOT NULL DEFAULT '已通过'"
            )
        if not has_reject_reason:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reject_reason VARCHAR(500) NULL AFTER review_status"
            )
        if not has_rejected_by:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN rejected_by BIGINT NULL AFTER reject_reason"
            )
        if not has_rejected_at:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN rejected_at DATETIME NULL AFTER rejected_by"
            )
        if not has_resubmitted_at:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN resubmitted_at DATETIME NULL AFTER rejected_at"
            )
        if not has_reverse_checkout_status:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_status "
                "ENUM('无','待审核','已驳回') NOT NULL DEFAULT '无' AFTER resubmitted_at"
            )
        if not has_reverse_checkout_reason:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_reason VARCHAR(500) NULL AFTER reverse_checkout_status"
            )
        if not has_reverse_checkout_requested_by:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_requested_by BIGINT NULL AFTER reverse_checkout_reason"
            )
        if not has_reverse_checkout_requested_at:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_requested_at DATETIME NULL AFTER reverse_checkout_requested_by"
            )
        if not has_reverse_checkout_rejected_by:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_rejected_by BIGINT NULL AFTER reverse_checkout_requested_at"
            )
        if not has_reverse_checkout_rejected_at:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN reverse_checkout_rejected_at DATETIME NULL AFTER reverse_checkout_rejected_by"
            )

        try:
            cursor.execute("ALTER TABLE orders MODIFY COLUMN payment_method VARCHAR(50) NULL")
        except Exception:
            pass
        cursor.execute(
            "UPDATE orders SET settlement_status='已结账' "
            "WHERE settlement_status IS NULL OR settlement_status=''"
        )
        cursor.execute(
            "UPDATE orders SET settlement_at = IFNULL(settlement_at, created_at), settlement_remind_until = NULL "
            "WHERE settlement_status='已结账'"
        )
        cursor.execute(
            "UPDATE orders SET payment_method = NULL "
            "WHERE settlement_status='未结账'"
        )
        cursor.execute(
            "UPDATE orders SET discount_amount = 0 "
            "WHERE discount_amount IS NULL"
        )
        cursor.execute(
            "UPDATE orders SET review_status='未审核' "
            "WHERE review_status='待审核'"
        )
        cursor.execute(
            "UPDATE orders SET review_status='未审核' "
            "WHERE settlement_status='未结账' AND (review_status IS NULL OR review_status='')"
        )
        cursor.execute(
            "UPDATE orders SET review_status='已通过' "
            "WHERE settlement_status='已结账' AND (review_status IS NULL OR review_status='')"
        )
        cursor.execute(
            "UPDATE orders SET reject_reason=NULL, rejected_by=NULL, rejected_at=NULL "
            "WHERE review_status<>'已驳回'"
        )
        cursor.execute(
            "ALTER TABLE orders MODIFY COLUMN review_status "
            "ENUM('未审核','已驳回','已通过') NOT NULL DEFAULT '已通过'"
        )
        cursor.execute(
            "UPDATE orders SET reverse_checkout_status='无' "
            "WHERE reverse_checkout_status IS NULL OR reverse_checkout_status=''"
        )
        db.commit()
    finally:
        db.close()


def ensure_order_recipient_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'recipient_name'")
        has_recipient_name = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'customer_phone'")
        has_customer_phone = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'recipient_address'")
        has_recipient_address = cursor.fetchone()

        if not has_recipient_name:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN recipient_name VARCHAR(100) NULL AFTER customer_name"
            )
        if not has_customer_phone:
            try:
                cursor.execute(
                    "ALTER TABLE orders ADD COLUMN customer_phone VARCHAR(50) NULL AFTER recipient_name"
                )
            except Exception as exc:
                ignore_duplicate_column(exc)
        if not has_recipient_address:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN recipient_address VARCHAR(255) NULL AFTER recipient_name"
            )

        cursor.execute(
            "UPDATE orders SET recipient_name = customer_name "
            "WHERE (recipient_name IS NULL OR recipient_name='') AND customer_name IS NOT NULL"
        )
        db.commit()
    finally:
        db.close()


def ensure_order_items_color_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM order_items LIKE 'color'")
        has_color = cursor.fetchone()
        if not has_color:
            cursor.execute(
                "ALTER TABLE order_items ADD COLUMN color VARCHAR(50) NULL AFTER amount"
            )
            db.commit()
    finally:
        db.close()


def ensure_order_item_detail_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        for table_name in ("order_items", "draft_order_items"):
            cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'product_name'")
            has_product_name = cursor.fetchone()
            cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'product_code'")
            has_product_code = cursor.fetchone()
            cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'english_name'")
            has_english_name = cursor.fetchone()
            cursor.execute(f"SHOW COLUMNS FROM {table_name} LIKE 'capacity'")
            has_capacity = cursor.fetchone()

            if not has_product_name:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN product_name VARCHAR(100) NULL AFTER product_id")
            if not has_product_code:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN product_code VARCHAR(100) NULL AFTER product_name")
            if not has_english_name:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN english_name VARCHAR(100) NULL AFTER product_code")
            if not has_capacity:
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN capacity VARCHAR(100) NULL AFTER english_name")

            cursor.execute(
                """
                SELECT CONSTRAINT_NAME
                FROM information_schema.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME = %s
                  AND COLUMN_NAME = 'product_id'
                  AND REFERENCED_TABLE_NAME IS NOT NULL
                """,
                (table_name,),
            )
            foreign_keys = cursor.fetchall() or []
            for foreign_key in foreign_keys:
                constraint_name = foreign_key[0] if isinstance(foreign_key, (list, tuple)) else foreign_key
                if not constraint_name:
                    continue
                cursor.execute(f"ALTER TABLE {table_name} DROP FOREIGN KEY {constraint_name}")

            try:
                cursor.execute(f"ALTER TABLE {table_name} MODIFY COLUMN product_id BIGINT NULL")
            except Exception:
                pass

        db.commit()
    finally:
        db.close()


def ensure_order_staff_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'order_clerk'")
        has_order_clerk = cursor.fetchone()
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'salesperson'")
        has_salesperson = cursor.fetchone()

        if not has_order_clerk:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN order_clerk VARCHAR(100) NULL AFTER clerk_id"
            )
        if not has_salesperson:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN salesperson VARCHAR(100) NULL AFTER order_clerk"
            )

        cursor.execute(
            "UPDATE orders o "
            "LEFT JOIN users u ON u.id = o.clerk_id "
            "SET o.order_clerk = IFNULL(u.username, o.order_clerk) "
            "WHERE (o.order_clerk IS NULL OR o.order_clerk='')"
        )
        db.commit()
    finally:
        db.close()


def ensure_order_draft_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS draft_orders (
              id BIGINT NOT NULL AUTO_INCREMENT,
              customer_name VARCHAR(100) NULL,
              customer_phone VARCHAR(50) NULL,
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS draft_order_items (
              id BIGINT NOT NULL AUTO_INCREMENT,
              draft_order_id BIGINT NOT NULL,
              product_id BIGINT NULL,
              product_name VARCHAR(100) NULL,
              product_code VARCHAR(100) NULL,
              english_name VARCHAR(100) NULL,
              capacity VARCHAR(100) NULL,
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
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        cursor.execute("SHOW COLUMNS FROM draft_orders LIKE 'customer_phone'")
        has_draft_customer_phone = cursor.fetchone()
        if not has_draft_customer_phone:
            try:
                cursor.execute(
                    "ALTER TABLE draft_orders ADD COLUMN customer_phone VARCHAR(50) NULL AFTER customer_name"
                )
            except Exception as exc:
                ignore_duplicate_column(exc)
        try:
            cursor.execute("ALTER TABLE draft_orders MODIFY COLUMN payment_method VARCHAR(50) NULL")
        except Exception:
            pass
        db.commit()
    finally:
        db.close()


def ensure_salesperson_schema():
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS salespersons (
              id BIGINT NOT NULL AUTO_INCREMENT,
              name VARCHAR(100) NOT NULL,
              created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (id),
              UNIQUE KEY uk_salespersons_name (name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
        db.commit()
    finally:
        db.close()


def run_schema_checks():
    ensure_order_settlement_schema()
    ensure_order_recipient_schema()
    ensure_order_items_color_schema()
    ensure_order_item_detail_schema()
    ensure_order_staff_schema()
    ensure_order_draft_schema()
    ensure_salesperson_schema()
