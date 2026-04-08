import MySQLdb
from flask import Blueprint, jsonify, request

from db import get_db
from utils.auth import auth_required

bp = Blueprint("products", __name__)


@bp.route("/api/products", methods=["GET"])
def get_products():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT * FROM products ORDER BY id")
    products = cursor.fetchall()
    db.close()
    return jsonify(products)


@bp.route("/api/products", methods=["POST"])
@auth_required()
def add_product():
    data = request.json or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"msg": "name is required"}), 400

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO products (name, english_name, product_code, capacity, unit) VALUES (%s,%s,%s,%s,%s)",
        (
            name,
            (data.get("english_name") or "").strip() or None,
            (data.get("product_code") or "").strip() or None,
            (data.get("capacity") or "").strip() or None,
            (data.get("unit") or "").strip() or None,
        ),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "product created"})


@bp.route("/api/products/<int:product_id>", methods=["PUT"])
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


@bp.route("/api/products/batch-delete", methods=["POST"])
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
