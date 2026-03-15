from flask import Flask, jsonify, request
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


@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO orders (order_number, customer_name, clerk_id, order_date, shipping_fee, total_amount, payment_method, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            data["order_number"],
            data["customer_name"],
            data["clerk_id"],
            data["order_date"],
            data["shipping_fee"],
            data["total_amount"],
            data["payment_method"],
            data.get("remark"),
        ),
    )
    order_id = cursor.lastrowid
    for item in data["items"]:
        cursor.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price, amount, sample_date, remark) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                order_id,
                item["product_id"],
                item["quantity"],
                item["unit_price"],
                item["amount"],
                item.get("sample_date"),
                item.get("remark"),
            ),
        )
    db.commit()
    db.close()
    return jsonify({"msg": "order created", "order_id": order_id})


@app.route("/api/orders/<int:order_id>", methods=["GET"])
def get_order(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    cursor.execute(
        "SELECT oi.*, p.name as product_name, p.product_code, p.english_name, p.capacity "
        "FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s",
        (order_id,),
    )
    items = cursor.fetchall()
    db.close()
    order["items"] = items
    return jsonify(order)


if __name__ == "__main__":
    print(f"[DB] host={MYSQL_HOST} port={MYSQL_PORT} db={MYSQL_DB} user={MYSQL_USER}")
    app.run(debug=True)
