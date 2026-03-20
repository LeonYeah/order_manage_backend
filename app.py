from datetime import datetime, timedelta

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
PAYMENT_METHODS = {"微信", "支付宝", "现金"}
REVIEW_STATUS_PENDING = "未审核"
REVIEW_STATUS_REJECTED = "已驳回"
REVIEW_STATUS_APPROVED = "已通过"


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
        db.commit()
    finally:
        db.close()


def parse_order_date(value):
    if not value:
        return datetime.now().date()

    if isinstance(value, datetime):
        return value.date()

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
    return "微信"


def normalize_review_status(value):
    if value == "待审核":
        return REVIEW_STATUS_PENDING
    if value in (REVIEW_STATUS_PENDING, REVIEW_STATUS_REJECTED, REVIEW_STATUS_APPROVED):
        return value
    return REVIEW_STATUS_APPROVED


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
    return order_row


def generate_order_number(cursor, order_date):
    prefix = order_date.strftime("%Y%m%d")
    cursor.execute(
        "SELECT order_number FROM orders WHERE order_number LIKE %s ORDER BY order_number DESC LIMIT 1",
        (f"{prefix}%",),
    )
    latest = cursor.fetchone()
    last_number = latest[0] if latest else None
    next_sequence = int(last_number[-4:]) + 1 if last_number else 1
    return f"{prefix}{next_sequence:04d}"


def normalize_role(role):
    if role in ("admin", "ADMIN", "管理员"):
        return "admin"
    if role in ("clerk", "CLERK", "制单员"):
        return "clerk"
    return role


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


@app.route("/api/products", methods=["GET"])
def get_products():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM products ORDER BY id")
    products = cursor.fetchall()
    db.close()
    return jsonify(products)


@app.route("/api/products", methods=["POST"])
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
@auth_required(required_role="admin")
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
    try:
        order_number = generate_order_number(cursor, order_date)
        clerk_id = data.get("clerk_id") or g.current_user.get("user_id")
        shipping_fee = float(data.get("shipping_fee") or 0)
        discount_amount = float(data.get("discount_amount") or 0)
        total_amount = float(data.get("total_amount") or 0)
        settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(None, data)
        review_status = get_default_review_status_for_settlement(settlement_status)
        remark = data.get("remark")

        cursor.execute(
            "INSERT INTO orders (order_number, customer_name, clerk_id, order_date, shipping_fee, discount_amount, total_amount, payment_method, settlement_status, settlement_remind_until, settlement_at, review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_number,
                customer_name,
                clerk_id,
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
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price, amount, sample_date, remark) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    order_id,
                    item["product_id"],
                    item["quantity"],
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    sample_date_value,
                    item.get("remark"),
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
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
    order_number = (request.args.get("order_number") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    reminder_only = request.args.get("reminder_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, u.username AS clerk_name, rb.username AS rejected_by_name",
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
        "SELECT o.*, u.username AS clerk_name, rb.username AS rejected_by_name FROM orders o "
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
        "SELECT oi.*, p.name as product_name, p.product_code, p.english_name, p.capacity "
        "FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s",
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
        "review_status, reject_reason, rejected_by, rejected_at, resubmitted_at "
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
                "UPDATE orders SET customer_name=%s, order_date=%s, shipping_status=%s, shipping_time=%s, "
                "tracking_number=%s, payment_method=%s, settlement_status=%s, settlement_remind_until=%s, settlement_at=%s, "
                "review_status=%s, reject_reason=%s, rejected_by=%s, rejected_at=%s, resubmitted_at=%s, "
                "total_amount=%s, shipping_fee=%s, discount_amount=%s, remark=%s WHERE id=%s",
                (
                    customer_name,
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
                    remark,
                    order_id,
                ),
            )

            cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
            for item in items:
                sample_date = item.get("sample_date")
                sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price, amount, sample_date, remark) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        order_id,
                        item["product_id"],
                        item["quantity"],
                        item.get("unit_price") or 0,
                        item.get("amount") or 0,
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
        "SELECT o.*, u.username AS clerk_name, rb.username AS rejected_by_name",
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
    app.run(debug=True)
