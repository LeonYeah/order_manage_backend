import MySQLdb
from flask import Blueprint, g, jsonify, request

from constants import SETTLEMENT_STATUS_UNSETTLED
from db import get_db
from services.common import get_username_by_user_id, normalize_role
from services.order_utils import (
    acquire_order_number_lock,
    build_settlement_fields,
    generate_order_number,
    get_default_review_status_for_settlement,
    normalize_item_text,
    normalize_payment_method,
    normalize_settlement_status,
    parse_order_date,
    release_order_number_lock,
)
from utils.auth import auth_required

bp = Blueprint("drafts", __name__)


@bp.route("/api/order-drafts", methods=["POST"])
@auth_required()
def create_order_draft():
    data = request.json or {}
    items = data.get("items") or []
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    try:
        order_date = parse_order_date(data.get("order_date"))
    except ValueError:
        return jsonify({"msg": "invalid order_date"}), 400

    db = get_db()
    cursor = db.cursor()
    try:
        clerk_id = data.get("clerk_id") or current_user_id
        if current_role != "admin":
            clerk_id = current_user_id
        order_clerk = get_username_by_user_id(cursor, clerk_id)
        customer_name = (data.get("customer_name") or "").strip() or None
        salesperson = (data.get("salesperson") or "").strip() or None
        recipient_name = (data.get("recipient_name") or "").strip() or None
        recipient_address = (data.get("recipient_address") or "").strip() or None
        shipping_fee = float(data.get("shipping_fee") or 0)
        discount_amount = float(data.get("discount_amount") or 0)
        total_amount = float(data.get("total_amount") or 0)
        settlement_status = normalize_settlement_status(data.get("settlement_status") or SETTLEMENT_STATUS_UNSETTLED)
        payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
        remark = (data.get("remark") or "").strip() or None

        cursor.execute(
            "INSERT INTO draft_orders (customer_name, salesperson, recipient_name, recipient_address, clerk_id, order_clerk, "
            "order_date, shipping_fee, discount_amount, total_amount, settlement_status, payment_method, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                customer_name,
                salesperson,
                recipient_name,
                recipient_address,
                clerk_id,
                order_clerk,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                settlement_status,
                payment_method,
                remark,
            ),
        )
        draft_id = cursor.lastrowid

        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            quantity = int(item.get("quantity") or 1)
            unit_price = float(item.get("unit_price") or 0)
            amount = float(item.get("amount") or 0)
            color = (item.get("color") or "").strip() or None
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            item_remark = (item.get("remark") or "").strip() or None
            cursor.execute(
                "INSERT INTO draft_order_items (draft_order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    draft_id,
                    item.get("product_id") or None,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    quantity,
                    unit_price,
                    amount,
                    color,
                    sample_date_value,
                    item_remark,
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "draft saved", "draft_id": draft_id})


@bp.route("/api/order-drafts", methods=["GET"])
@auth_required()
def get_order_drafts():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    clerk_id = request.args.get("clerk_id", type=int)
    user_name = (request.args.get("user_name") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()

    query = [
        "SELECT d.*, u.username AS clerk_name, COUNT(di.id) AS item_count",
        "FROM draft_orders d",
        "LEFT JOIN users u ON u.id = d.clerk_id",
        "LEFT JOIN draft_order_items di ON di.draft_order_id = d.id",
        "WHERE 1=1",
    ]
    params = []

    if current_role != "admin":
        query.append("AND d.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND d.clerk_id=%s")
        params.append(clerk_id)
    if user_name:
        query.append("AND u.username LIKE %s")
        params.append(f"%{user_name}%")

    if start_date:
        try:
            start_date_obj = parse_order_date(start_date)
        except ValueError:
            return jsonify({"msg": "invalid start_date"}), 400
        query.append("AND d.order_date >= %s")
        params.append(start_date_obj.strftime("%Y-%m-%d"))

    if end_date:
        try:
            end_date_obj = parse_order_date(end_date)
        except ValueError:
            return jsonify({"msg": "invalid end_date"}), 400
        query.append("AND d.order_date <= %s")
        params.append(end_date_obj.strftime("%Y-%m-%d"))

    query.append("GROUP BY d.id")
    query.append("ORDER BY d.updated_at DESC, d.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    drafts = cursor.fetchall()
    db.close()
    return jsonify(drafts)


@bp.route("/api/order-drafts/<int:draft_id>", methods=["DELETE"])
@auth_required()
def delete_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, clerk_id FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute("DELETE FROM draft_orders WHERE id=%s", (draft_id,))
    db.commit()
    db.close()
    return jsonify({"msg": "draft deleted"})


@bp.route("/api/order-drafts/<int:draft_id>", methods=["GET"])
@auth_required()
def get_order_draft_detail(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT d.*, u.username AS clerk_name FROM draft_orders d LEFT JOIN users u ON u.id=d.clerk_id WHERE d.id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT di.*, "
        "COALESCE(di.product_name, p.name) AS product_name, "
        "COALESCE(di.product_code, p.product_code) AS product_code, "
        "COALESCE(di.english_name, p.english_name) AS english_name, "
        "COALESCE(di.capacity, p.capacity) AS capacity "
        "FROM draft_order_items di LEFT JOIN products p ON p.id=di.product_id "
        "WHERE di.draft_order_id=%s ORDER BY di.id ASC",
        (draft_id,),
    )
    items = cursor.fetchall()
    db.close()
    draft["items"] = items
    return jsonify(draft)


@bp.route("/api/order-drafts/<int:draft_id>", methods=["PUT"])
@auth_required()
def update_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    data = request.json or {}
    items = data.get("items") or []

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    customer_name = (data.get("customer_name") or "").strip()
    if not customer_name:
        db.close()
        return jsonify({"msg": "customer_name is required"}), 400
    if not items:
        db.close()
        return jsonify({"msg": "items are required"}), 400

    try:
        order_date = parse_order_date(data.get("order_date"))
    except ValueError:
        db.close()
        return jsonify({"msg": "invalid order_date"}), 400

    clerk_id = draft.get("clerk_id")
    order_clerk = get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (data.get("salesperson") or "").strip() or None
    recipient_name = (data.get("recipient_name") or customer_name).strip()
    recipient_address = (data.get("recipient_address") or "").strip() or None
    shipping_fee = float(data.get("shipping_fee") or 0)
    discount_amount = float(data.get("discount_amount") or 0)
    total_amount = float(data.get("total_amount") or 0)
    settlement_status = normalize_settlement_status(data.get("settlement_status") or draft.get("settlement_status"))
    payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
    remark = (data.get("remark") or "").strip() or None

    try:
        cursor_plain.execute(
            "UPDATE draft_orders SET customer_name=%s, salesperson=%s, recipient_name=%s, recipient_address=%s, "
            "order_clerk=%s, order_date=%s, shipping_fee=%s, discount_amount=%s, total_amount=%s, "
            "settlement_status=%s, payment_method=%s, remark=%s WHERE id=%s",
            (
                customer_name,
                salesperson,
                recipient_name,
                recipient_address,
                order_clerk,
                order_date.strftime("%Y-%m-%d"),
                shipping_fee,
                discount_amount,
                total_amount,
                settlement_status,
                payment_method,
                remark,
                draft_id,
            ),
        )
        cursor_plain.execute("DELETE FROM draft_order_items WHERE draft_order_id=%s", (draft_id,))

        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO draft_order_items (draft_order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    draft_id,
                    item.get("product_id") or None,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    int(item.get("quantity") or 1),
                    float(item.get("unit_price") or 0),
                    float(item.get("amount") or 0),
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    (item.get("remark") or "").strip() or None,
                ),
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "draft updated"})


@bp.route("/api/order-drafts/<int:draft_id>/confirm", methods=["POST"])
@auth_required()
def confirm_order_draft(draft_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM draft_orders WHERE id=%s", (draft_id,))
    draft = cursor.fetchone()
    if not draft:
        db.close()
        return jsonify({"msg": "draft not found"}), 404
    if current_role != "admin" and draft.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark "
        "FROM draft_order_items WHERE draft_order_id=%s ORDER BY id ASC",
        (draft_id,),
    )
    items = cursor.fetchall()
    if not items:
        db.close()
        return jsonify({"msg": "draft items are required"}), 400

    customer_name = (draft.get("customer_name") or "").strip()
    if not customer_name:
        db.close()
        return jsonify({"msg": "customer_name is required"}), 400

    order_date = parse_order_date(draft.get("order_date"))
    settlement_status = normalize_settlement_status(draft.get("settlement_status"))
    payment_method = normalize_payment_method(draft.get("payment_method"), settlement_status)
    settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(
        None,
        {"settlement_status": settlement_status, "payment_method": payment_method},
    )
    review_status = get_default_review_status_for_settlement(settlement_status)
    clerk_id = draft.get("clerk_id")
    order_clerk = (draft.get("order_clerk") or "").strip() or get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (draft.get("salesperson") or "").strip() or None
    recipient_name = (draft.get("recipient_name") or customer_name).strip()
    recipient_address = (draft.get("recipient_address") or "").strip() or None
    shipping_fee = float(draft.get("shipping_fee") or 0)
    discount_amount = float(draft.get("discount_amount") or 0)
    total_amount = float(draft.get("total_amount") or 0)
    remark = (draft.get("remark") or "").strip() or None
    order_lock_acquired = False

    try:
        acquire_order_number_lock(cursor_plain, timeout_seconds=10)
        order_lock_acquired = True
        order_number = generate_order_number(cursor_plain, order_date)
        cursor_plain.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, "
            "shipping_fee, discount_amount, total_amount, payment_method, settlement_status, settlement_remind_until, settlement_at, review_status, "
            "reject_reason, rejected_by, rejected_at, resubmitted_at, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                order_number,
                customer_name,
                recipient_name,
                recipient_address,
                clerk_id,
                order_clerk,
                salesperson,
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
        order_id = cursor_plain.lastrowid

        for item in items:
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    order_id,
                    item.get("product_id") or None,
                    normalize_item_text(item.get("product_name")),
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item.get("quantity") or 1,
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )

        cursor_plain.execute("DELETE FROM draft_orders WHERE id=%s", (draft_id,))
        db.commit()
    except RuntimeError as exc:
        db.rollback()
        if str(exc) == "order_number_lock_timeout":
            return jsonify({"msg": "订单编号生成繁忙，请稍后重试"}), 503
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        if order_lock_acquired:
            release_order_number_lock(cursor_plain)
        db.close()

    return jsonify({"msg": "draft confirmed", "order_id": order_id, "order_number": order_number})
