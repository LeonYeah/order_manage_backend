from flask import Blueprint, jsonify, request

from db import get_db
from utils.auth import login_user

bp = Blueprint("auth", __name__)


@bp.route("/api/login", methods=["POST"])
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
