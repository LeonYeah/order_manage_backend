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
