import MySQLdb
from flask import Blueprint, g, jsonify, request

from db import get_db
from services.common import normalize_role
from utils.auth import auth_required, hash_password

bp = Blueprint("users", __name__)


@bp.route("/api/users", methods=["GET"])
@auth_required(required_role="admin")
def get_users():
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, username, role, created_at FROM users")
    users = cursor.fetchall()
    db.close()
    return jsonify(users)


@bp.route("/api/users/<int:user_id>", methods=["GET"])
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


@bp.route("/api/users", methods=["POST"])
@auth_required(required_role="admin")
def add_user():
    data = request.json or {}
    username = (data.get("username") or "").strip()
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


@bp.route("/api/users/<int:user_id>/password", methods=["PUT"])
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


@bp.route("/api/users/<int:user_id>", methods=["DELETE"])
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
