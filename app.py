import os
from datetime import date, datetime, timedelta

from flask import Flask, g, jsonify, request
from flask_cors import CORS
import MySQLdb

from config import (
    MYSQL_CHARSET,
    MYSQL_DB,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USER,
    SECRET_KEY,
)
from utils.auth import auth_required, hash_password, login_user

app = Flask(__name__)
CORS(app)
app.config["SECRET_KEY"] = SECRET_KEY

SETTLEMENT_STATUS_UNSETTLED = "未结账"
SETTLEMENT_STATUS_SETTLED = "已结账"
SETTLEMENT_REMIND_DAYS = 3
PAYMENT_METHODS = {"支付宝", "微信", "银城漆行二维码", "银城漆行对公", "艺彩对公", "百绘彩对公"}
REVIEW_STATUS_PENDING = "未审核"
REVIEW_STATUS_REJECTED = "已驳回"
REVIEW_STATUS_APPROVED = "已通过"
REVERSE_CHECKOUT_STATUS_NONE = "无"
REVERSE_CHECKOUT_STATUS_PENDING = "待审核"
REVERSE_CHECKOUT_STATUS_REJECTED = "已驳回"
ORDER_NUMBER_LOCK_NAME = "orders_order_number_lock"


def get_db():
    return MySQLdb.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        passwd=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset=MYSQL_CHARSET,
    )


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
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'recipient_address'")
        has_recipient_address = cursor.fetchone()

        if not has_recipient_name:
            cursor.execute(
                "ALTER TABLE orders ADD COLUMN recipient_name VARCHAR(100) NULL AFTER customer_name"
            )
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
        cursor.execute("UPDATE orders SET salesperson=NULL WHERE salesperson IS NOT NULL")
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


def parse_order_date(value):
    if not value:
        return datetime.now().date()

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return datetime.now().date()

        for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(normalized, pattern).date()
            except ValueError:
                continue

        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()

    raise ValueError("invalid_order_date")


def normalize_item_text(value):
    return (value or "").strip() or None


def normalize_settlement_status(value):
    if value == SETTLEMENT_STATUS_UNSETTLED:
        return SETTLEMENT_STATUS_UNSETTLED
    return SETTLEMENT_STATUS_SETTLED


def normalize_payment_method(value, settlement_status):
    method = (value or "").strip()
    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        return None
    if method and method in PAYMENT_METHODS:
        return method
    return "支付宝"


def normalize_review_status(value):
    if value == "待审核":
        return REVIEW_STATUS_PENDING
    if value in (REVIEW_STATUS_PENDING, REVIEW_STATUS_REJECTED, REVIEW_STATUS_APPROVED):
        return value
    return REVIEW_STATUS_APPROVED


def normalize_reverse_checkout_status(value):
    if value in (REVERSE_CHECKOUT_STATUS_PENDING, REVERSE_CHECKOUT_STATUS_REJECTED):
        return value
    return REVERSE_CHECKOUT_STATUS_NONE


def build_settlement_fields(existing_order, data):
    settlement_status = normalize_settlement_status(data.get("settlement_status") or (existing_order or {}).get("settlement_status"))
    payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
    existing_status = normalize_settlement_status((existing_order or {}).get("settlement_status"))
    existing_remind_until = (existing_order or {}).get("settlement_remind_until")
    existing_settlement_at = (existing_order or {}).get("settlement_at")
    now = datetime.now()

    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        settlement_at = None
        settlement_remind_until = existing_remind_until
        if existing_status != SETTLEMENT_STATUS_UNSETTLED or not settlement_remind_until:
            settlement_remind_until = now + timedelta(days=SETTLEMENT_REMIND_DAYS)
    else:
        settlement_remind_until = None
        settlement_at = existing_settlement_at if existing_status == SETTLEMENT_STATUS_SETTLED else now

    return settlement_status, payment_method, settlement_remind_until, settlement_at


def get_default_review_status_for_settlement(settlement_status):
    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        return REVIEW_STATUS_PENDING
    return REVIEW_STATUS_APPROVED


def serialize_order_flags(order_row):
    settlement_status = normalize_settlement_status(order_row.get("settlement_status"))
    remind_until = order_row.get("settlement_remind_until")
    remind_active = bool(
        settlement_status == SETTLEMENT_STATUS_UNSETTLED
        and remind_until
        and remind_until >= datetime.now()
    )
    order_row["settlement_status"] = settlement_status
    order_row["need_settlement_remind"] = remind_active
    order_row["settlement_remind_days_left"] = (
        max(0, (remind_until - datetime.now()).days + (1 if (remind_until - datetime.now()).seconds > 0 else 0))
        if remind_active else 0
    )
    order_row["review_status"] = normalize_review_status(order_row.get("review_status"))
    order_row["reverse_checkout_status"] = normalize_reverse_checkout_status(order_row.get("reverse_checkout_status"))
    return order_row


def generate_order_number(cursor, order_date):
    prefix = order_date.strftime("%Y%m%d")
    cursor.execute(
        "SELECT order_number FROM orders WHERE order_number LIKE %s ORDER BY order_number DESC LIMIT 1",
        (f"{prefix}%",),
    )
    latest = cursor.fetchone()
    last_number = _get_first_column(latest) if latest else None
    next_sequence = int(last_number[-4:]) + 1 if last_number else 1
    return f"{prefix}{next_sequence:04d}"


def acquire_order_number_lock(cursor, timeout_seconds=10):
    cursor.execute("SELECT GET_LOCK(%s, %s)", (ORDER_NUMBER_LOCK_NAME, timeout_seconds))
    result = cursor.fetchone()
    lock_status = _get_first_column(result)
    if lock_status != 1:
        raise RuntimeError("order_number_lock_timeout")


def release_order_number_lock(cursor):
    try:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (ORDER_NUMBER_LOCK_NAME,))
    except Exception:
        pass


def _get_first_column(row):
    if row is None:
        return None
    if isinstance(row, (list, tuple)):
        return row[0] if row else None
    if isinstance(row, dict):
        for _, value in row.items():
            return value
        return None
    return row


def normalize_role(role):
    if role in ("admin", "ADMIN", "管理员"):
        return "admin"
    if role in ("clerk", "CLERK", "制单员"):
        return "clerk"
    return role


def get_username_by_user_id(cursor, user_id):
    cursor.execute("SELECT username FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    if not user:
        return ""
    if isinstance(user, (list, tuple)):
        return user[0] or ""
    return user.get("username") or ""


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"msg": "username or password is required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id, password, role FROM users WHERE username=%s", (username,))
    user = cursor.fetchone()
    db.close()

    token = login_user(user, password)
    if token:
        return jsonify({"token": token})
    return jsonify({"msg": "invalid username or password"}), 401


@app.route("/api/users", methods=["GET"])
@auth_required(required_role="admin")
def get_users():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, username, role, created_at FROM users")
    users = cursor.fetchall()
    db.close()
    return jsonify(users)


@app.route("/api/users/<int:user_id>", methods=["GET"])
@auth_required()
def get_user(user_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    if current_role != "admin" and current_user_id != user_id:
        return jsonify({"msg": "forbidden"}), 403

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, username, role, created_at FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    db.close()

    if not user:
        return jsonify({"msg": "user not found"}), 404
    return jsonify(user)


@app.route("/api/users", methods=["POST"])
@auth_required(required_role="admin")
def add_user():
    data = request.json or {}
    username = data.get("username")
    password = data.get("password")
    role = data.get("role")

    if not username or not password or not role:
        return jsonify({"msg": "username, password and role are required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO users (username,password,role) VALUES (%s,%s,%s)",
        (username, hash_password(password), role),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "user created"})


@app.route("/api/users/<int:user_id>/password", methods=["PUT"])
@auth_required(required_role="admin")
def update_user_password(user_id):
    data = request.json or {}
    password = data.get("password")

    if not password:
        return jsonify({"msg": "password is required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()

    if not user:
        db.close()
        return jsonify({"msg": "user not found"}), 404

    cursor.execute(
        "UPDATE users SET password=%s WHERE id=%s",
        (hash_password(password), user_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "password updated"})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@auth_required(required_role="admin")
def delete_user(user_id):
    current_user_id = g.current_user.get("user_id")
    if current_user_id == user_id:
        return jsonify({"msg": "cannot delete current user"}), 400

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, username FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()

    if not user:
        db.close()
        return jsonify({"msg": "user not found"}), 404

    cursor.execute("SELECT COUNT(1) AS total FROM orders WHERE clerk_id=%s OR rejected_by=%s", (user_id, user_id))
    order_usage = cursor.fetchone()
    cursor.execute("SELECT COUNT(1) AS total FROM draft_orders WHERE clerk_id=%s", (user_id,))
    draft_usage = cursor.fetchone()

    order_count = (order_usage or {}).get("total", 0)
    draft_count = (draft_usage or {}).get("total", 0)
    if order_count or draft_count:
        db.close()
        return jsonify({"msg": "该用户已关联订单或草稿，无法删除"}), 400

    write_cursor = db.cursor()
    write_cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
    db.commit()
    db.close()
    return jsonify({"msg": "user deleted"})


@app.route("/api/salespersons", methods=["GET"])
@auth_required()
def get_salespersons():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, name, created_at FROM salespersons ORDER BY id DESC")
    salespersons = cursor.fetchall()
    db.close()
    return jsonify(salespersons)


@app.route("/api/salespersons", methods=["POST"])
@auth_required(required_role="admin")
def add_salesperson():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"msg": "salesperson name is required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM salespersons WHERE name=%s", (name,))
    exists = cursor.fetchone()
    if exists:
        db.close()
        return jsonify({"msg": "salesperson already exists"}), 400

    cursor.execute("INSERT INTO salespersons (name) VALUES (%s)", (name,))
    db.commit()
    db.close()
    return jsonify({"msg": "salesperson created"})


@app.route("/api/salespersons/<int:salesperson_id>", methods=["DELETE"])
@auth_required(required_role="admin")
def delete_salesperson(salesperson_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, name FROM salespersons WHERE id=%s", (salesperson_id,))
    salesperson = cursor.fetchone()
    if not salesperson:
        db.close()
        return jsonify({"msg": "salesperson not found"}), 404

    name = salesperson.get("name")
    cursor.execute("SELECT COUNT(1) AS total FROM orders WHERE salesperson=%s", (name,))
    order_usage = cursor.fetchone()
    cursor.execute("SELECT COUNT(1) AS total FROM draft_orders WHERE salesperson=%s", (name,))
    draft_usage = cursor.fetchone()
    if (order_usage or {}).get("total", 0) or (draft_usage or {}).get("total", 0):
        db.close()
        return jsonify({"msg": "该业务员已关联订单或草稿，无法删除"}), 400

    write_cursor = db.cursor()
    write_cursor.execute("DELETE FROM salespersons WHERE id=%s", (salesperson_id,))
    db.commit()
    db.close()
    return jsonify({"msg": "salesperson deleted"})


@app.route("/api/products", methods=["GET"])
def get_products():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM products ORDER BY id")
    products = cursor.fetchall()
    db.close()
    return jsonify(products)


@app.route("/api/products", methods=["POST"])
@auth_required()
def add_product():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO products (name, english_name, product_code, capacity, unit) VALUES (%s,%s,%s,%s,%s)",
        (
            data["name"],
            data.get("english_name"),
            data.get("product_code"),
            data.get("capacity"),
            data.get("unit"),
        ),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "product created"})


@app.route("/api/products/<int:product_id>", methods=["PUT"])
@auth_required()
def update_product(product_id):
    data = request.json or {}
    name = (data.get("name") or "").strip()
    english_name = (data.get("english_name") or "").strip() or None
    product_code = (data.get("product_code") or "").strip() or None
    capacity = (data.get("capacity") or "").strip() or None
    unit = (data.get("unit") or "").strip() or None

    if not name:
        return jsonify({"msg": "name is required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id FROM products WHERE id=%s", (product_id,))
    product = cursor.fetchone()
    if not product:
        db.close()
        return jsonify({"msg": "product not found"}), 404

    cursor.execute(
        "UPDATE products SET name=%s, english_name=%s, product_code=%s, capacity=%s, unit=%s WHERE id=%s",
        (name, english_name, product_code, capacity, unit, product_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "product updated"})


@app.route("/api/products/batch-delete", methods=["POST"])
@auth_required()
def batch_delete_products():
    data = request.json or {}
    raw_ids = data.get("ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        return jsonify({"msg": "ids are required"}), 400

    product_ids = []
    for value in raw_ids:
        try:
            product_id = int(value)
        except (TypeError, ValueError):
            return jsonify({"msg": "invalid ids"}), 400
        if product_id > 0 and product_id not in product_ids:
            product_ids.append(product_id)

    if not product_ids:
        return jsonify({"msg": "ids are required"}), 400

    placeholders = ",".join(["%s"] * len(product_ids))
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    try:
        cursor.execute(
            f"SELECT DISTINCT p.id, p.name "
            f"FROM products p JOIN order_items oi ON oi.product_id=p.id "
            f"WHERE p.id IN ({placeholders})",
            product_ids,
        )
        used_products = cursor.fetchall()
        if used_products:
            used_names = [item.get("name") or str(item.get("id")) for item in used_products]
            return jsonify({"msg": f"以下商品已被订单使用，无法删除：{','.join(used_names)}"}), 400

        cursor.execute(
            f"DELETE FROM products WHERE id IN ({placeholders})",
            product_ids,
        )
        deleted_count = cursor.rowcount
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "products deleted", "deleted_count": deleted_count})


@app.route("/api/order-drafts", methods=["POST"])
@auth_required()
def create_order_draft():
    data = request.json or {}
    items = data.get("items") or []
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    try:
        order_date = parse_order_date(data.get("order_date"))
    except ValueError:
        return jsonify({"msg": "invalid order_date"}), 400

    db = get_db()
    cursor = db.cursor()
    try:
        clerk_id = data.get("clerk_id") or current_user_id
        if current_role != "admin":
            clerk_id = current_user_id
        order_clerk = get_username_by_user_id(cursor, clerk_id)
        customer_name = (data.get("customer_name") or "").strip() or None
        salesperson = (data.get("salesperson") or "").strip() or None
        recipient_name = (data.get("recipient_name") or "").strip() or None
        recipient_address = (data.get("recipient_address") or "").strip() or None
        shipping_fee = float(data.get("shipping_fee") or 0)
        discount_amount = float(data.get("discount_amount") or 0)
        total_amount = float(data.get("total_amount") or 0)
        settlement_status = normalize_settlement_status(data.get("settlement_status") or SETTLEMENT_STATUS_UNSETTLED)
        payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
        remark = (data.get("remark") or "").strip() or None

        cursor.execute(
            "INSERT INTO draft_orders (customer_name, salesperson, recipient_name, recipient_address, clerk_id, order_clerk, "
            "order_date, shipping_fee, discount_amount, total_amount, settlement_status, payment_method, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                customer_name,
                salesperson,
                recipient_name,
                recipient_address,
                clerk_id,
                order_clerk,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                settlement_status,
                payment_method,
                remark,
            ),
        )
        draft_id = cursor.lastrowid

        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            quantity = int(item.get("quantity") or 1)
            unit_price = float(item.get("unit_price") or 0)
            amount = float(item.get("amount") or 0)
            color = (item.get("color") or "").strip() or None
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            item_remark = (item.get("remark") or "").strip() or None
            cursor.execute(
                "INSERT INTO draft_order_items (draft_order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    draft_id,
                    item.get("product_id") or None,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    quantity,
                    unit_price,
                    amount,
                    color,
                    sample_date_value,
                    item_remark,
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "draft saved", "draft_id": draft_id})


@app.route("/api/order-drafts", methods=["GET"])
@auth_required()
def get_order_drafts():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    clerk_id = request.args.get("clerk_id", type=int)
    user_name = (request.args.get("user_name") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    query = [
        "SELECT d.*, u.username AS clerk_name, COUNT(di.id) AS item_count",
        "FROM draft_orders d",
        "LEFT JOIN users u ON u.id = d.clerk_id",
        "LEFT JOIN draft_order_items di ON di.draft_order_id = d.id",
        "WHERE 1=1",
    ]
    params = []

    if current_role != "admin":
        query.append("AND d.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND d.clerk_id=%s")
        params.append(clerk_id)
    if user_name:
        query.append("AND u.username LIKE %s")
        params.append(f"%{user_name}%")

    if start_date:
        try:
            start_date_obj = parse_order_date(start_date)
        except ValueError:
            return jsonify({"msg": "invalid start_date"}), 400
        query.append("AND d.order_date >= %s")
        params.append(start_date_obj.strftime("%Y-%m-%d"))

    if end_date:
        try:
            end_date_obj = parse_order_date(end_date)
        except ValueError:
            return jsonify({"msg": "invalid end_date"}), 400
        query.append("AND d.order_date <= %s")
        params.append(end_date_obj.strftime("%Y-%m-%d"))

    query.append("GROUP BY d.id")
    query.append("ORDER BY d.updated_at DESC, d.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    drafts = cursor.fetchall()
    db.close()
    return jsonify(drafts)


@app.route("/api/order-drafts/<int:draft_id>", methods=["DELETE"])
@auth_required()
def delete_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, clerk_id FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute("DELETE FROM draft_orders WHERE id=%s", (draft_id,))
    db.commit()
    db.close()
    return jsonify({"msg": "draft deleted"})


@app.route("/api/order-drafts/<int:draft_id>", methods=["GET"])
@auth_required()
def get_order_draft_detail(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT d.*, u.username AS clerk_name FROM draft_orders d LEFT JOIN users u ON u.id=d.clerk_id WHERE d.id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT di.*, "
        "COALESCE(di.product_name, p.name) AS product_name, "
        "COALESCE(di.product_code, p.product_code) AS product_code, "
        "COALESCE(di.english_name, p.english_name) AS english_name, "
        "COALESCE(di.capacity, p.capacity) AS capacity "
        "FROM draft_order_items di LEFT JOIN products p ON p.id=di.product_id "
        "WHERE di.draft_order_id=%s ORDER BY di.id ASC",
        (draft_id,),
    )
    items = cursor.fetchall()
    db.close()
    draft["items"] = items
    return jsonify(draft)


@app.route("/api/order-drafts/<int:draft_id>", methods=["PUT"])
@auth_required()
def update_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    data = request.json or {}
    items = data.get("items") or []

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    customer_name = (data.get("customer_name") or "").strip()
    if not customer_name:
        db.close()
        return jsonify({"msg": "customer_name is required"}), 400
    if not items:
        db.close()
        return jsonify({"msg": "items are required"}), 400

    try:
        order_date = parse_order_date(data.get("order_date"))
    except ValueError:
        db.close()
        return jsonify({"msg": "invalid order_date"}), 400

    clerk_id = draft.get("clerk_id")
    order_clerk = get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (data.get("salesperson") or "").strip() or None
    recipient_name = (data.get("recipient_name") or customer_name).strip()
    recipient_address = (data.get("recipient_address") or "").strip() or None
    shipping_fee = float(data.get("shipping_fee") or 0)
    discount_amount = float(data.get("discount_amount") or 0)
    total_amount = float(data.get("total_amount") or 0)
    settlement_status = normalize_settlement_status(data.get("settlement_status") or draft.get("settlement_status"))
    payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
    remark = (data.get("remark") or "").strip() or None

    try:
        cursor_plain.execute(
            "UPDATE draft_orders SET customer_name=%s, salesperson=%s, recipient_name=%s, recipient_address=%s, "
            "order_clerk=%s, order_date=%s, shipping_fee=%s, discount_amount=%s, total_amount=%s, "
            "settlement_status=%s, payment_method=%s, remark=%s WHERE id=%s",
            (
                customer_name,
                salesperson,
                recipient_name,
                recipient_address,
                order_clerk,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                settlement_status,
                payment_method,
                remark,
                draft_id,
            ),
        )
        cursor_plain.execute("DELETE FROM draft_order_items WHERE draft_order_id=%s", (draft_id,))

        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            product_id = item.get("product_id") or None
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO draft_order_items (draft_order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    draft_id,
                    product_id,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    int(item.get("quantity") or 1),
                    float(item.get("unit_price") or 0),
                    float(item.get("amount") or 0),
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    (item.get("remark") or "").strip() or None,
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "draft updated"})


@app.route("/api/order-drafts/<int:draft_id>/confirm", methods=["POST"])
@auth_required()
def confirm_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark "
        "FROM draft_order_items WHERE draft_order_id=%s ORDER BY id ASC",
        (draft_id,),
    )
    items = cursor.fetchall()
    if not items:
        db.close()
        return jsonify({"msg": "draft items are required"}), 400

    customer_name = (draft.get("customer_name") or "").strip()
    if not customer_name:
        db.close()
        return jsonify({"msg": "customer_name is required"}), 400

    order_date = parse_order_date(draft.get("order_date"))
    settlement_status = normalize_settlement_status(draft.get("settlement_status"))
    payment_method = normalize_payment_method(draft.get("payment_method"), settlement_status)
    settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(
        None,
        {"settlement_status": settlement_status, "payment_method": payment_method},
    )
    review_status = get_default_review_status_for_settlement(settlement_status)
    clerk_id = draft.get("clerk_id")
    order_clerk = (draft.get("order_clerk") or "").strip() or get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (draft.get("salesperson") or "").strip() or None
    recipient_name = (draft.get("recipient_name") or customer_name).strip()
    recipient_address = (draft.get("recipient_address") or "").strip() or None
    shipping_fee = float(draft.get("shipping_fee") or 0)
    discount_amount = float(draft.get("discount_amount") or 0)
    total_amount = float(draft.get("total_amount") or 0)
    remark = (draft.get("remark") or "").strip() or None
    order_lock_acquired = False

    try:
        acquire_order_number_lock(cursor_plain, timeout_seconds=10)
        order_lock_acquired = True
        order_number = generate_order_number(cursor_plain, order_date)
        cursor_plain.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, "
            "shipping_fee, discount_amount, total_amount, payment_method, settlement_status, settlement_remind_until, settlement_at, review_status, "
            "reject_reason, rejected_by, rejected_at, resubmitted_at, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_number,
                customer_name,
                recipient_name,
                recipient_address,
                clerk_id,
                order_clerk,
                salesperson,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                payment_method,
                settlement_status,
                settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                review_status,
                None,
                None,
                None,
                None,
                remark,
            ),
        )
        order_id = cursor_plain.lastrowid

        for item in items:
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    order_id,
                    item.get("product_id") or None,
                    normalize_item_text(item.get("product_name")),
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item.get("quantity") or 1,
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )

        cursor_plain.execute("DELETE FROM draft_orders WHERE id=%s", (draft_id,))
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        if str(exc) == "order_number_lock_timeout":
            return jsonify({"msg": "订单编号生成繁忙，请稍后重试"}), 503
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        if order_lock_acquired:
            release_order_number_lock(cursor_plain)
        db.close()

    return jsonify({"msg": "draft confirmed", "order_id": order_id, "order_number": order_number})


@app.route("/api/orders/next-number", methods=["GET"])
@auth_required()
def get_next_order_number():
    date_value = request.args.get("date")
    order_date = parse_order_date(date_value)

    db = get_db()
    cursor = db.cursor()
    order_number = generate_order_number(cursor, order_date)
    db.close()

    return jsonify({"order_number": order_number})


@app.route("/api/orders", methods=["POST"])
@auth_required()
def create_order():
    data = request.json or {}
    items = data.get("items") or []
    customer_name = (data.get("customer_name") or "").strip()

    if not customer_name:
        return jsonify({"msg": "customer_name is required"}), 400
    if not items:
        return jsonify({"msg": "items are required"}), 400

    try:
        order_date = parse_order_date(data.get("order_date"))
    except ValueError:
        return jsonify({"msg": "invalid order_date"}), 400

    db = get_db()
    cursor = db.cursor()
    order_lock_acquired = False
    try:
        acquire_order_number_lock(cursor, timeout_seconds=10)
        order_lock_acquired = True
        order_number = generate_order_number(cursor, order_date)
        clerk_id = data.get("clerk_id") or g.current_user.get("user_id")
        order_clerk = get_username_by_user_id(cursor, clerk_id)
        salesperson = (data.get("salesperson") or "").strip() or None
        shipping_fee = float(data.get("shipping_fee") or 0)
        discount_amount = float(data.get("discount_amount") or 0)
        total_amount = float(data.get("total_amount") or 0)
        recipient_name = (data.get("recipient_name") or customer_name).strip()
        recipient_address = (data.get("recipient_address") or "").strip() or None
        settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(None, data)
        review_status = get_default_review_status_for_settlement(settlement_status)
        remark = data.get("remark")

        cursor.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, shipping_fee, discount_amount, total_amount, payment_method, settlement_status, settlement_remind_until, settlement_at, review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_number,
                customer_name,
                recipient_name,
                recipient_address,
                clerk_id,
                order_clerk,
                salesperson,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                payment_method,
                settlement_status,
                settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                review_status,
                None,
                None,
                None,
                None,
                remark,
            ),
        )
        order_id = cursor.lastrowid
        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    order_id,
                    item.get("product_id") or None,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item["quantity"],
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        if str(exc) == "order_number_lock_timeout":
            return jsonify({"msg": "订单编号生成繁忙，请稍后重试"}), 503
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        if order_lock_acquired:
            release_order_number_lock(cursor)
        db.close()

    return jsonify({"msg": "order created", "order_id": order_id, "order_number": order_number})


@app.route("/api/orders", methods=["GET"])
@auth_required()
def get_orders():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    shipping_status = (request.args.get("shipping_status") or "").strip()
    payment_method = (request.args.get("payment_method") or "").strip()
    settlement_status = (request.args.get("settlement_status") or "").strip()
    review_status = (request.args.get("review_status") or "").strip()
    salesperson = (request.args.get("salesperson") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    reminder_only = request.args.get("reminder_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users rb ON rb.id = o.rejected_by",
        "WHERE 1=1",
    ]
    params = []

    if current_role != "admin":
        query.append("AND o.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND o.clerk_id=%s")
        params.append(clerk_id)

    if customer_name:
        query.append("AND o.customer_name LIKE %s")
        params.append(f"%{customer_name}%")

    if shipping_status:
        query.append("AND o.shipping_status=%s")
        params.append(shipping_status)

    if payment_method:
        query.append("AND o.payment_method=%s")
        params.append(payment_method)

    if settlement_status:
        query.append("AND o.settlement_status=%s")
        params.append(settlement_status)

    if review_status:
        query.append("AND o.review_status=%s")
        params.append(review_status)

    if salesperson:
        query.append("AND o.salesperson LIKE %s")
        params.append(f"%{salesperson}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if start_date:
        try:
            start_date_obj = parse_order_date(start_date)
        except ValueError:
            return jsonify({"msg": "invalid start_date"}), 400
        query.append("AND o.order_date >= %s")
        params.append(start_date_obj.strftime("%Y-%m-%d"))

    if end_date:
        try:
            end_date_obj = parse_order_date(end_date)
        except ValueError:
            return jsonify({"msg": "invalid end_date"}), 400
        query.append("AND o.order_date <= %s")
        params.append(end_date_obj.strftime("%Y-%m-%d"))

    if reminder_only:
        query.append("AND o.settlement_status=%s")
        query.append("AND o.settlement_remind_until IS NOT NULL")
        query.append("AND o.settlement_remind_until >= %s")
        params.append(SETTLEMENT_STATUS_UNSETTLED)
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    query.append("ORDER BY o.order_date DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@app.route("/api/orders/<int:order_id>", methods=["GET"])
@auth_required()
def get_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name FROM orders o "
        "LEFT JOIN users u ON u.id = o.clerk_id "
        "LEFT JOIN users rb ON rb.id = o.rejected_by WHERE o.id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT oi.*, "
        "COALESCE(oi.product_name, p.name) AS product_name, "
        "COALESCE(oi.product_code, p.product_code) AS product_code, "
        "COALESCE(oi.english_name, p.english_name) AS english_name, "
        "COALESCE(oi.capacity, p.capacity) AS capacity "
        "FROM order_items oi LEFT JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s",
        (order_id,),
    )
    items = cursor.fetchall()
    db.close()
    order["items"] = items
    serialize_order_flags(order)
    return jsonify(order)


@app.route("/api/orders/<int:order_id>", methods=["PUT"])
@auth_required()
def update_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    data = request.json or {}

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, clerk_id, shipping_status, settlement_status, settlement_remind_until, settlement_at, "
        "review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, reverse_checkout_status "
        "FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    try:
        if "items" in data:
            if normalize_settlement_status(order.get("settlement_status")) == SETTLEMENT_STATUS_SETTLED:
                return jsonify({"msg": "已结账订单需先提交反结账申请并经管理员审核后才能修改"}), 400
            items = data.get("items") or []
            customer_name = (data.get("customer_name") or "").strip()
            if not customer_name:
                return jsonify({"msg": "customer_name is required"}), 400
            if not items:
                return jsonify({"msg": "items are required"}), 400

            try:
                order_date = parse_order_date(data.get("order_date"))
            except ValueError:
                return jsonify({"msg": "invalid order_date"}), 400

            shipping_status = data.get("shipping_status") or order.get("shipping_status") or "未发货"
            tracking_number = (data.get("tracking_number") or "").strip() or None
            shipping_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if shipping_status == "已发货" else None
            shipping_fee = float(data.get("shipping_fee") or 0)
            discount_amount = float(data.get("discount_amount") or 0)
            total_amount = float(data.get("total_amount") or 0)
            recipient_name = (data.get("recipient_name") or customer_name).strip()
            recipient_address = (data.get("recipient_address") or "").strip() or None
            salesperson = (data.get("salesperson") or "").strip() or None
            settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(order, data)
            review_status = normalize_review_status(order.get("review_status"))
            reject_reason = order.get("reject_reason")
            rejected_by = order.get("rejected_by")
            rejected_at = order.get("rejected_at")
            resubmitted_at = order.get("resubmitted_at")
            old_settlement_status = normalize_settlement_status(order.get("settlement_status"))
            if settlement_status == SETTLEMENT_STATUS_SETTLED:
                review_status = REVIEW_STATUS_APPROVED
                reject_reason = None
                rejected_by = None
                rejected_at = None
            elif old_settlement_status == SETTLEMENT_STATUS_SETTLED:
                review_status = REVIEW_STATUS_PENDING
                reject_reason = None
                rejected_by = None
                rejected_at = None
            elif review_status == REVIEW_STATUS_REJECTED and current_role != "admin":
                review_status = REVIEW_STATUS_PENDING
                reject_reason = None
                rejected_by = None
                rejected_at = None
                resubmitted_at = datetime.now()
            remark = data.get("remark")

            cursor.execute(
                "UPDATE orders SET customer_name=%s, recipient_name=%s, recipient_address=%s, order_date=%s, shipping_status=%s, shipping_time=%s, "
                "tracking_number=%s, payment_method=%s, settlement_status=%s, settlement_remind_until=%s, settlement_at=%s, "
                "review_status=%s, reject_reason=%s, rejected_by=%s, rejected_at=%s, resubmitted_at=%s, "
                "total_amount=%s, shipping_fee=%s, discount_amount=%s, salesperson=%s, remark=%s WHERE id=%s",
                (
                    customer_name,
                    recipient_name,
                    recipient_address,
                    order_date.strftime("%Y-%m-%d"),
                    shipping_status,
                    shipping_time,
                    tracking_number,
                    payment_method,
                    settlement_status,
                    settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                    settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                    review_status,
                    reject_reason,
                    rejected_by,
                    rejected_at.strftime("%Y-%m-%d %H:%M:%S") if rejected_at else None,
                    resubmitted_at.strftime("%Y-%m-%d %H:%M:%S") if resubmitted_at else None,
                    total_amount,
                    shipping_fee,
                    discount_amount,
                    salesperson,
                    remark,
                    order_id,
                ),
            )

            cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
            for item in items:
                product_name = normalize_item_text(item.get("product_name"))
                if not product_name:
                    continue
                sample_date = item.get("sample_date")
                sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        order_id,
                        item.get("product_id") or None,
                        product_name,
                        normalize_item_text(item.get("product_code")),
                        normalize_item_text(item.get("english_name")),
                        normalize_item_text(item.get("capacity")),
                        item["quantity"],
                        item.get("unit_price") or 0,
                        item.get("amount") or 0,
                        (item.get("color") or "").strip() or None,
                        sample_date_value,
                        item.get("remark"),
                    ),
                )
        else:
            shipping_status = data.get("shipping_status") or order.get("shipping_status") or "未发货"
            tracking_number = (data.get("tracking_number") or "").strip() or None
            remark = data.get("remark")
            shipping_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if shipping_status == "已发货" else None

            cursor.execute(
                "UPDATE orders SET shipping_status=%s, shipping_time=%s, tracking_number=%s, remark=%s WHERE id=%s",
                (shipping_status, shipping_time, tracking_number, remark, order_id),
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return jsonify({"msg": "order updated"})


@app.route("/api/orders/reverse-checkout", methods=["GET"])
@auth_required()
def get_reverse_checkout_orders():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    reverse_status = (request.args.get("reverse_status") or "").strip()
    rejected_only = request.args.get("rejected_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name,",
        "req.username AS reverse_checkout_requested_by_name,",
        "rej.username AS reverse_checkout_rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users req ON req.id = o.reverse_checkout_requested_by",
        "LEFT JOIN users rej ON rej.id = o.reverse_checkout_rejected_by",
        "WHERE o.settlement_status=%s",
        "AND o.reverse_checkout_status<>%s",
    ]
    params = [SETTLEMENT_STATUS_SETTLED, REVERSE_CHECKOUT_STATUS_NONE]

    if current_role != "admin":
        query.append("AND o.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND o.clerk_id=%s")
        params.append(clerk_id)

    if customer_name:
        query.append("AND o.customer_name LIKE %s")
        params.append(f"%{customer_name}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if reverse_status:
        query.append("AND o.reverse_checkout_status=%s")
        params.append(reverse_status)

    if rejected_only:
        query.append("AND o.reverse_checkout_status=%s")
        params.append(REVERSE_CHECKOUT_STATUS_REJECTED)

    query.append("ORDER BY o.reverse_checkout_requested_at DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@app.route("/api/orders/<int:order_id>/reverse-checkout", methods=["POST"])
@auth_required()
def request_reverse_checkout(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, clerk_id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可提交反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) == REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "该订单已提交反结账审核，请勿重复提交"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET reverse_checkout_status=%s, reverse_checkout_reason=NULL, "
        "reverse_checkout_requested_by=%s, reverse_checkout_requested_at=%s, "
        "reverse_checkout_rejected_by=NULL, reverse_checkout_rejected_at=NULL WHERE id=%s",
        (REVERSE_CHECKOUT_STATUS_PENDING, current_user_id, now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout requested"})


@app.route("/api/orders/<int:order_id>/reverse-checkout/reject", methods=["POST"])
@auth_required(required_role="admin")
def reject_reverse_checkout(order_id):
    data = request.json or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"msg": "驳回原因不能为空"}), 400

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可驳回反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) != REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "当前订单没有待审核的反结账申请"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET reverse_checkout_status=%s, reverse_checkout_reason=%s, "
        "reverse_checkout_rejected_by=%s, reverse_checkout_rejected_at=%s WHERE id=%s",
        (REVERSE_CHECKOUT_STATUS_REJECTED, reason, g.current_user.get("user_id"), now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout rejected"})


@app.route("/api/orders/<int:order_id>/reverse-checkout/approve", methods=["POST"])
@auth_required(required_role="admin")
def approve_reverse_checkout(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可审核反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) != REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "当前订单没有待审核的反结账申请"}), 400

    now = datetime.now()
    remind_until = now + timedelta(days=SETTLEMENT_REMIND_DAYS)
    cursor.execute(
        "UPDATE orders SET settlement_status=%s, payment_method=NULL, settlement_remind_until=%s, settlement_at=NULL, "
        "review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL, resubmitted_at=NULL, "
        "reverse_checkout_status=%s, reverse_checkout_reason=NULL, reverse_checkout_requested_by=NULL, "
        "reverse_checkout_requested_at=NULL, reverse_checkout_rejected_by=NULL, reverse_checkout_rejected_at=NULL "
        "WHERE id=%s",
        (
            SETTLEMENT_STATUS_UNSETTLED,
            remind_until.strftime("%Y-%m-%d %H:%M:%S"),
            REVIEW_STATUS_PENDING,
            REVERSE_CHECKOUT_STATUS_NONE,
            order_id,
        ),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout approved"})


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
@auth_required()
def delete_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, clerk_id, shipping_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    shipping_status = (order.get("shipping_status") or "").strip() or "未发货"
    if shipping_status == "已发货":
        db.close()
        return jsonify({"msg": "已发货订单不可删除"}), 400

    try:
        cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
        cursor.execute("DELETE FROM orders WHERE id=%s", (order_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "order deleted"})


@app.route("/api/orders/<int:order_id>/copy", methods=["POST"])
@auth_required()
def copy_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    source_order = cursor.fetchone()
    if not source_order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and source_order.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark "
        "FROM order_items WHERE order_id=%s ORDER BY id ASC",
        (order_id,),
    )
    source_items = cursor.fetchall()
    if not source_items:
        db.close()
        return jsonify({"msg": "source order items not found"}), 400

    new_order_date = datetime.now().date()
    settlement_status = normalize_settlement_status(source_order.get("settlement_status"))
    payment_method = normalize_payment_method(source_order.get("payment_method"), settlement_status)
    settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(
        None,
        {
            "settlement_status": settlement_status,
            "payment_method": payment_method,
        },
    )
    review_status = get_default_review_status_for_settlement(settlement_status)
    shipping_status = "未发货"
    shipping_time = None
    tracking_number = None
    clerk_id = current_user_id
    order_clerk = get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (source_order.get("salesperson") or "").strip() or None
    order_lock_acquired = False

    try:
        acquire_order_number_lock(cursor_plain, timeout_seconds=10)
        order_lock_acquired = True
        new_order_number = generate_order_number(cursor_plain, new_order_date)
        cursor_plain.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, "
            "shipping_status, shipping_time, tracking_number, shipping_fee, discount_amount, total_amount, payment_method, "
            "settlement_status, settlement_remind_until, settlement_at, review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                new_order_number,
                source_order.get("customer_name"),
                source_order.get("recipient_name"),
                source_order.get("recipient_address"),
                clerk_id,
                order_clerk,
                salesperson,
                new_order_date.strftime("%Y-%m-%d"),
                shipping_status,
                shipping_time,
                tracking_number,
                source_order.get("shipping_fee") or 0,
                source_order.get("discount_amount") or 0,
                source_order.get("total_amount") or 0,
                payment_method,
                settlement_status,
                settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                review_status,
                None,
                None,
                None,
                None,
                source_order.get("remark"),
            ),
        )
        new_order_id = cursor_plain.lastrowid

        for item in source_items:
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    new_order_id,
                    item.get("product_id") or None,
                    normalize_item_text(item.get("product_name")),
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item.get("quantity"),
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )

        db.commit()
    except RuntimeError as exc:
        db.rollback()
        if str(exc) == "order_number_lock_timeout":
            return jsonify({"msg": "订单编号生成繁忙，请稍后重试"}), 503
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        if order_lock_acquired:
            release_order_number_lock(cursor_plain)
        db.close()

    return jsonify({"msg": "order copied", "order_id": new_order_id, "order_number": new_order_number})


@app.route("/api/orders/review", methods=["GET"])
@auth_required()
def get_orders_for_review():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    review_status = (request.args.get("review_status") or "").strip()
    rejected_only = request.args.get("rejected_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users rb ON rb.id = o.rejected_by",
        "WHERE o.settlement_status=%s",
    ]
    params = [SETTLEMENT_STATUS_UNSETTLED]

    if current_role != "admin":
        query.append("AND o.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND o.clerk_id=%s")
        params.append(clerk_id)

    if customer_name:
        query.append("AND o.customer_name LIKE %s")
        params.append(f"%{customer_name}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if review_status:
        query.append("AND o.review_status=%s")
        params.append(review_status)

    if rejected_only:
        query.append("AND o.review_status=%s")
        params.append(REVIEW_STATUS_REJECTED)

    query.append("ORDER BY o.order_date DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@app.route("/api/orders/<int:order_id>/reject", methods=["POST"])
@auth_required(required_role="admin")
def reject_order(order_id):
    data = request.json or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"msg": "驳回原因不能为空"}), 400

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, settlement_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可驳回"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=%s, rejected_by=%s, rejected_at=%s WHERE id=%s",
        (REVIEW_STATUS_REJECTED, reason, g.current_user.get("user_id"), now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order rejected"})


@app.route("/api/orders/<int:order_id>/resubmit", methods=["POST"])
@auth_required()
def resubmit_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, clerk_id, settlement_status, review_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可重新提交"}), 400
    if normalize_review_status(order.get("review_status")) != REVIEW_STATUS_REJECTED:
        db.close()
        return jsonify({"msg": "仅已驳回订单可重新提交"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL, resubmitted_at=%s WHERE id=%s",
        (REVIEW_STATUS_PENDING, now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order resubmitted"})


@app.route("/api/orders/<int:order_id>/approve", methods=["POST"])
@auth_required(required_role="admin")
def approve_order(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, settlement_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可审核通过"}), 400

    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL WHERE id=%s",
        (REVIEW_STATUS_APPROVED, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order approved"})


if __name__ == "__main__":
    print(f"[DB] host={MYSQL_HOST} port={MYSQL_PORT} db={MYSQL_DB} user={MYSQL_USER}")
    ensure_order_settlement_schema()
    ensure_order_recipient_schema()
    ensure_order_items_color_schema()
    ensure_order_item_detail_schema()
    ensure_order_staff_schema()
    ensure_order_draft_schema()
    ensure_salesperson_schema()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
