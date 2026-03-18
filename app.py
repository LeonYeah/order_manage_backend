from datetime import datetime

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


def get_db():
    return MySQLdb.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        passwd=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset=MYSQL_CHARSET,
    )


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
        total_amount = float(data.get("total_amount") or 0)
        payment_method = data.get("payment_method") or "微信"
        remark = data.get("remark")

        cursor.execute(
            "INSERT INTO orders (order_number, customer_name, clerk_id, order_date, shipping_fee, total_amount, payment_method, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_number,
                customer_name,
                clerk_id,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                total_amount,
                payment_method,
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
    order_number = (request.args.get("order_number") or "").strip()

    query = [
        "SELECT o.*, u.username AS clerk_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
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

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    query.append("ORDER BY o.order_date DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = cursor.fetchall()
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
        "SELECT o.*, u.username AS clerk_name FROM orders o "
        "LEFT JOIN users u ON u.id = o.clerk_id WHERE o.id=%s",
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
    cursor.execute("SELECT id, clerk_id, shipping_status FROM orders WHERE id=%s", (order_id,))
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
            total_amount = float(data.get("total_amount") or 0)
            payment_method = data.get("payment_method") or "微信"
            remark = data.get("remark")

            cursor.execute(
                "UPDATE orders SET customer_name=%s, order_date=%s, shipping_status=%s, shipping_time=%s, "
                "tracking_number=%s, payment_method=%s, total_amount=%s, shipping_fee=%s, remark=%s WHERE id=%s",
                (
                    customer_name,
                    order_date.strftime("%Y-%m-%d"),
                    shipping_status,
                    shipping_time,
                    tracking_number,
                    payment_method,
                    total_amount,
                    shipping_fee,
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


if __name__ == "__main__":
    print(f"[DB] host={MYSQL_HOST} port={MYSQL_PORT} db={MYSQL_DB} user={MYSQL_USER}")
    app.run(debug=True)
