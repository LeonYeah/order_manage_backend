import MySQLdb
from flask import Blueprint, jsonify, request

from db import get_db
from utils.auth import auth_required

bp = Blueprint("salespersons", __name__)


@bp.route("/api/salespersons", methods=["GET"])
@auth_required()
def get_salespersons():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, name, created_at FROM salespersons ORDER BY id DESC")
    salespersons = cursor.fetchall()
    db.close()
    return jsonify(salespersons)


@bp.route("/api/salespersons", methods=["POST"])
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


@bp.route("/api/salespersons/<int:salesperson_id>", methods=["DELETE"])
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
