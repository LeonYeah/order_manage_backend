from flask import Flask, request, jsonify
from flask_cors import CORS
import MySQLdb
import bcrypt
import jwt
import datetime

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = 'your_secret_key'

# 数据库连接
def get_db():
    return MySQLdb.connect(
        host='localhost',    # MySQL 主机
        user='root',         # MySQL 用户名
        passwd='root',       # MySQL 密码
        db='product_order_system',
        charset='utf8mb4'
    )

# ---------------- 用户登录 ----------------
@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data['username']
    password = data['password'].encode('utf-8')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT id, password, role FROM users WHERE username=%s", (username,))
    user = cursor.fetchone()
    db.close()
    if user and bcrypt.checkpw(password, user[1].encode('utf-8')):
        token = jwt.encode({'user_id': user[0], 'role': user[2], 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=8)}, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({'token': token})
    return jsonify({'msg':'用户名或密码错误'}), 401

# ---------------- 获取用户信息 ----------------
@app.route('/api/users', methods=['GET'])
def get_users():
    token = request.headers.get('Authorization')
    try:
        payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
        if payload['role'] != 'admin':
            return jsonify({'msg':'权限不足'}), 403
    except:
        return jsonify({'msg':'无效token'}), 401

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, username, role, created_at FROM users")
    users = cursor.fetchall()
    db.close()
    return jsonify(users)

# ---------------- 添加用户 ----------------
@app.route('/api/users', methods=['POST'])
def add_user():
    token = request.headers.get('Authorization')
    payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
    if payload['role'] != 'admin':
        return jsonify({'msg':'权限不足'}), 403

    data = request.json
    username = data['username']
    password = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt())
    role = data['role']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO users (username,password,role) VALUES (%s,%s,%s)", (username, password.decode(), role))
    db.commit()
    db.close()
    return jsonify({'msg':'用户添加成功'})

# ---------------- 获取商品列表 ----------------
@app.route('/api/products', methods=['GET'])
def get_products():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM products ORDER BY id")
    products = cursor.fetchall()
    db.close()
    return jsonify(products)

# ---------------- 添加商品 ----------------
@app.route('/api/products', methods=['POST'])
def add_product():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO products (name, english_name, product_code, capacity, unit) VALUES (%s,%s,%s,%s,%s)",
                   (data['name'], data.get('english_name'), data.get('product_code'), data.get('capacity'), data.get('unit')))
    db.commit()
    db.close()
    return jsonify({'msg':'商品添加成功'})

# ---------------- 新建订单 ----------------
@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO orders (order_number, customer_name, clerk_id, order_date, shipping_fee, total_amount, payment_method, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (data['order_number'], data['customer_name'], data['clerk_id'], data['order_date'], data['shipping_fee'], data['total_amount'], data['payment_method'], data.get('remark'))
    )
    order_id = cursor.lastrowid
    for item in data['items']:
        cursor.execute(
            "INSERT INTO order_items (order_id, product_id, quantity, unit_price, amount, sample_date, remark) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (order_id, item['product_id'], item['quantity'], item['unit_price'], item['amount'], item.get('sample_date'), item.get('remark'))
        )
    db.commit()
    db.close()
    return jsonify({'msg':'订单创建成功','order_id':order_id})


@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    cursor.execute("SELECT oi.*, p.name as product_name, p.product_code, p.english_name, p.capacity \
                    FROM order_items oi JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s", (order_id,))
    items = cursor.fetchall()
    db.close()
    order['items'] = items
    return jsonify(order)

if __name__ == '__main__':
    app.run(debug=True)