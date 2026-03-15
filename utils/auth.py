from datetime import datetime, timedelta
from functools import wraps

import bcrypt
import jwt
from flask import current_app, g, jsonify, request

try:
    from config import SECRET_KEY as DEFAULT_SECRET_KEY
except ImportError:
    DEFAULT_SECRET_KEY = "your_secret_key"


DEFAULT_EXPIRE_HOURS = 8


def _get_secret_key(secret_key=None):
    if secret_key:
        return secret_key

    app = current_app._get_current_object() if current_app else None
    if app and app.config.get("SECRET_KEY"):
        return app.config["SECRET_KEY"]

    return DEFAULT_SECRET_KEY


def hash_password(password):
    password_bytes = _to_bytes(password)
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(password, hashed_password):
    password_bytes = _to_bytes(password)
    hashed_bytes = _to_bytes(hashed_password)
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def generate_token(user_id, role, expire_hours=DEFAULT_EXPIRE_HOURS, secret_key=None, extra_claims=None):
    payload = {
        "user_id": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=expire_hours),
    }
    if extra_claims:
        payload.update(extra_claims)

    token = jwt.encode(payload, _get_secret_key(secret_key), algorithm="HS256")
    if isinstance(token, bytes):
        return token.decode("utf-8")
    return token


def decode_token(token, secret_key=None):
    return jwt.decode(token, _get_secret_key(secret_key), algorithms=["HS256"])


def extract_token_from_header(auth_header=None):
    auth_header = auth_header or request.headers.get("Authorization", "")
    if not auth_header:
        raise ValueError("missing_token")

    parts = auth_header.strip().split()
    if len(parts) == 1:
        return parts[0]

    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]

    raise ValueError("invalid_authorization_header")


def get_current_user(required_role=None, secret_key=None):
    token = extract_token_from_header()
    payload = decode_token(token, secret_key=secret_key)

    if required_role and payload.get("role") != required_role:
        raise PermissionError("forbidden")

    return payload


def login_user(user, password, password_index=1, id_index=0, role_index=2, secret_key=None):
    if not user:
        return None

    stored_password = user[password_index]
    if not verify_password(password, stored_password):
        return None

    return generate_token(
        user_id=user[id_index],
        role=user[role_index],
        secret_key=secret_key,
    )


def auth_required(required_role=None, secret_key=None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            try:
                payload = get_current_user(required_role=required_role, secret_key=secret_key)
            except ValueError:
                return jsonify({"msg": "invalid authorization header"}), 401
            except jwt.ExpiredSignatureError:
                return jsonify({"msg": "token expired"}), 401
            except jwt.InvalidTokenError:
                return jsonify({"msg": "invalid token"}), 401
            except PermissionError:
                return jsonify({"msg": "forbidden"}), 403

            g.current_user = payload
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def _to_bytes(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("password must be str or bytes")
