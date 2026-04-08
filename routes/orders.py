from datetime import datetime, timedelta

import MySQLdb
from flask import Blueprint, g, jsonify, request

from constants import (
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_REJECTED,
    REVERSE_CHECKOUT_STATUS_NONE,
    REVERSE_CHECKOUT_STATUS_PENDING,
    REVERSE_CHECKOUT_STATUS_REJECTED,
    SETTLEMENT_REMIND_DAYS,
    SETTLEMENT_STATUS_SETTLED,
    SETTLEMENT_STATUS_UNSETTLED,
)
from db import get_db
from services.common import get_username_by_user_id, normalize_role
from services.order_utils import (
    acquire_order_number_lock,
    build_settlement_fields,
    generate_order_number,
    get_default_review_status_for_settlement,
    normalize_item_text,
    normalize_payment_method,
    normalize_review_status,
    normalize_reverse_checkout_status,
    normalize_settlement_status,
    parse_order_date,
    release_order_number_lock,
    serialize_order_flags,
)
from utils.auth import auth_required

bp = Blueprint("orders", __name__)


@bp.route("/api/orders/next-number", methods=["GET"])
@auth_required()
def get_next_order_number():
    date_value = request.args.get("date")
    order_date = parse_order_date(date_value)

    db = get_db()
    cursor = db.cursor()
    order_number = generate_order_number(cursor, order_date)
    db.close()

    return jsonify({"order_number": order_number})


@bp.route("/api/orders", methods=["POST"])
@auth_required()
def create_order():
    data = request.json or {}
    items = data.get("items") or []
    customer_name = (data.get("customer_name") or "").strip()
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

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
    order_lock_acquired = False
    try:
        acquire_order_number_lock(cursor, timeout_seconds=10)
        order_lock_acquired = True
        order_number = generate_order_number(cursor, order_date)
        clerk_id = data.get("clerk_id") or current_user_id
        if current_role != "admin":
            clerk_id = current_user_id
        order_clerk = get_username_by_user_id(cursor, clerk_id)
        salesperson = (data.get("salesperson") or "").strip() or None
        shipping_fee = float(data.get("shipping_fee") or 0)
        discount_amount = float(data.get("discount_amount") or 0)
        total_amount = float(data.get("total_amount") or 0)
        recipient_name = (data.get("recipient_name") or customer_name).strip()
        recipient_address = (data.get("recipient_address") or "").strip() or None
        settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(None, data)
        review_status = get_default_review_status_for_settlement(settlement_status)
        remark = data.get("remark")

        cursor.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, shipping_fee, discount_amount, total_amount, payment_method, settlement_status, settlement_remind_until, settlement_at, review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
        order_id = cursor.lastrowid
        for item in items:
            product_name = normalize_item_text(item.get("product_name"))
            if not product_name:
                continue
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    order_id,
                    item.get("product_id") or None,
                    product_name,
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item["quantity"],
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )
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
            release_order_number_lock(cursor)
        db.close()

    return jsonify({"msg": "order created", "order_id": order_id, "order_number": order_number})


@bp.route("/api/orders", methods=["GET"])
@auth_required()
def get_orders():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    shipping_status = (request.args.get("shipping_status") or "").strip()
    payment_method = (request.args.get("payment_method") or "").strip()
    settlement_status = (request.args.get("settlement_status") or "").strip()
    review_status = (request.args.get("review_status") or "").strip()
    salesperson = (request.args.get("salesperson") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    start_date = (request.args.get("start_date") or "").strip()
    end_date = (request.args.get("end_date") or "").strip()
    reminder_only = request.args.get("reminder_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users rb ON rb.id = o.rejected_by",
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

    if settlement_status:
        query.append("AND o.settlement_status=%s")
        params.append(settlement_status)

    if review_status:
        query.append("AND o.review_status=%s")
        params.append(review_status)

    if salesperson:
        query.append("AND o.salesperson LIKE %s")
        params.append(f"%{salesperson}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if start_date:
        try:
            start_date_obj = parse_order_date(start_date)
        except ValueError:
            return jsonify({"msg": "invalid start_date"}), 400
        query.append("AND o.order_date >= %s")
        params.append(start_date_obj.strftime("%Y-%m-%d"))

    if end_date:
        try:
            end_date_obj = parse_order_date(end_date)
        except ValueError:
            return jsonify({"msg": "invalid end_date"}), 400
        query.append("AND o.order_date <= %s")
        params.append(end_date_obj.strftime("%Y-%m-%d"))

    if reminder_only:
        query.append("AND o.settlement_status=%s")
        query.append("AND o.settlement_remind_until IS NOT NULL")
        query.append("AND o.settlement_remind_until >= %s")
        params.append(SETTLEMENT_STATUS_UNSETTLED)
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    query.append("ORDER BY o.order_date DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@bp.route("/api/orders/<int:order_id>", methods=["GET"])
@auth_required()
def get_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name FROM orders o "
        "LEFT JOIN users u ON u.id = o.clerk_id "
        "LEFT JOIN users rb ON rb.id = o.rejected_by WHERE o.id=%s",
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
        "SELECT oi.*, "
        "COALESCE(oi.product_name, p.name) AS product_name, "
        "COALESCE(oi.product_code, p.product_code) AS product_code, "
        "COALESCE(oi.english_name, p.english_name) AS english_name, "
        "COALESCE(oi.capacity, p.capacity) AS capacity "
        "FROM order_items oi LEFT JOIN products p ON oi.product_id=p.id WHERE oi.order_id=%s",
        (order_id,),
    )
    items = cursor.fetchall()
    db.close()
    order["items"] = items
    serialize_order_flags(order)
    return jsonify(order)


@bp.route("/api/orders/<int:order_id>", methods=["PUT"])
@auth_required()
def update_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")
    data = request.json or {}

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, clerk_id, shipping_status, settlement_status, settlement_remind_until, settlement_at, "
        "review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, reverse_checkout_status "
        "FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    try:
        if "items" in data:
            if normalize_settlement_status(order.get("settlement_status")) == SETTLEMENT_STATUS_SETTLED:
                return jsonify({"msg": "已结账订单需先提交反结账申请并经管理员审核后才能修改"}), 400
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
            discount_amount = float(data.get("discount_amount") or 0)
            total_amount = float(data.get("total_amount") or 0)
            recipient_name = (data.get("recipient_name") or customer_name).strip()
            recipient_address = (data.get("recipient_address") or "").strip() or None
            salesperson = (data.get("salesperson") or "").strip() or None
            settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(order, data)
            review_status = normalize_review_status(order.get("review_status"))
            reject_reason = order.get("reject_reason")
            rejected_by = order.get("rejected_by")
            rejected_at = order.get("rejected_at")
            resubmitted_at = order.get("resubmitted_at")
            old_settlement_status = normalize_settlement_status(order.get("settlement_status"))
            if settlement_status == SETTLEMENT_STATUS_SETTLED:
                review_status = REVIEW_STATUS_APPROVED
                reject_reason = None
                rejected_by = None
                rejected_at = None
            elif old_settlement_status == SETTLEMENT_STATUS_SETTLED:
                review_status = REVIEW_STATUS_PENDING
                reject_reason = None
                rejected_by = None
                rejected_at = None
            elif review_status == REVIEW_STATUS_REJECTED and current_role != "admin":
                review_status = REVIEW_STATUS_PENDING
                reject_reason = None
                rejected_by = None
                rejected_at = None
                resubmitted_at = datetime.now()
            remark = data.get("remark")

            cursor.execute(
                "UPDATE orders SET customer_name=%s, recipient_name=%s, recipient_address=%s, order_date=%s, shipping_status=%s, shipping_time=%s, "
                "tracking_number=%s, payment_method=%s, settlement_status=%s, settlement_remind_until=%s, settlement_at=%s, "
                "review_status=%s, reject_reason=%s, rejected_by=%s, rejected_at=%s, resubmitted_at=%s, "
                "total_amount=%s, shipping_fee=%s, discount_amount=%s, salesperson=%s, remark=%s WHERE id=%s",
                (
                    customer_name,
                    recipient_name,
                    recipient_address,
                    order_date.strftime("%Y-%m-%d"),
                    shipping_status,
                    shipping_time,
                    tracking_number,
                    payment_method,
                    settlement_status,
                    settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                    settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                    review_status,
                    reject_reason,
                    rejected_by,
                    rejected_at.strftime("%Y-%m-%d %H:%M:%S") if rejected_at else None,
                    resubmitted_at.strftime("%Y-%m-%d %H:%M:%S") if resubmitted_at else None,
                    total_amount,
                    shipping_fee,
                    discount_amount,
                    salesperson,
                    remark,
                    order_id,
                ),
            )

            cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
            for item in items:
                product_name = normalize_item_text(item.get("product_name"))
                if not product_name:
                    continue
                sample_date = item.get("sample_date")
                sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
                cursor.execute(
                    "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        order_id,
                        item.get("product_id") or None,
                        product_name,
                        normalize_item_text(item.get("product_code")),
                        normalize_item_text(item.get("english_name")),
                        normalize_item_text(item.get("capacity")),
                        item["quantity"],
                        item.get("unit_price") or 0,
                        item.get("amount") or 0,
                        (item.get("color") or "").strip() or None,
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


@bp.route("/api/orders/reverse-checkout", methods=["GET"])
@auth_required()
def get_reverse_checkout_orders():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    reverse_status = (request.args.get("reverse_status") or "").strip()
    rejected_only = request.args.get("rejected_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name,",
        "req.username AS reverse_checkout_requested_by_name,",
        "rej.username AS reverse_checkout_rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users req ON req.id = o.reverse_checkout_requested_by",
        "LEFT JOIN users rej ON rej.id = o.reverse_checkout_rejected_by",
        "WHERE o.settlement_status=%s",
        "AND o.reverse_checkout_status<>%s",
    ]
    params = [SETTLEMENT_STATUS_SETTLED, REVERSE_CHECKOUT_STATUS_NONE]

    if current_role != "admin":
        query.append("AND o.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND o.clerk_id=%s")
        params.append(clerk_id)

    if customer_name:
        query.append("AND o.customer_name LIKE %s")
        params.append(f"%{customer_name}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if reverse_status:
        query.append("AND o.reverse_checkout_status=%s")
        params.append(reverse_status)

    if rejected_only:
        query.append("AND o.reverse_checkout_status=%s")
        params.append(REVERSE_CHECKOUT_STATUS_REJECTED)

    query.append("ORDER BY o.reverse_checkout_requested_at DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@bp.route("/api/orders/<int:order_id>/reverse-checkout", methods=["POST"])
@auth_required()
def request_reverse_checkout(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, clerk_id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可提交反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) == REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "该订单已提交反结账审核，请勿重复提交"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET reverse_checkout_status=%s, reverse_checkout_reason=NULL, "
        "reverse_checkout_requested_by=%s, reverse_checkout_requested_at=%s, "
        "reverse_checkout_rejected_by=NULL, reverse_checkout_rejected_at=NULL WHERE id=%s",
        (REVERSE_CHECKOUT_STATUS_PENDING, current_user_id, now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout requested"})


@bp.route("/api/orders/<int:order_id>/reverse-checkout/reject", methods=["POST"])
@auth_required(required_role="admin")
def reject_reverse_checkout(order_id):
    data = request.json or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"msg": "驳回原因不能为空"}), 400

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可驳回反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) != REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "当前订单没有待审核的反结账申请"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET reverse_checkout_status=%s, reverse_checkout_reason=%s, "
        "reverse_checkout_rejected_by=%s, reverse_checkout_rejected_at=%s WHERE id=%s",
        (REVERSE_CHECKOUT_STATUS_REJECTED, reason, g.current_user.get("user_id"), now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout rejected"})


@bp.route("/api/orders/<int:order_id>/reverse-checkout/approve", methods=["POST"])
@auth_required(required_role="admin")
def approve_reverse_checkout(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(
        "SELECT id, settlement_status, reverse_checkout_status FROM orders WHERE id=%s",
        (order_id,),
    )
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_SETTLED:
        db.close()
        return jsonify({"msg": "仅已结账订单可审核反结账申请"}), 400
    if normalize_reverse_checkout_status(order.get("reverse_checkout_status")) != REVERSE_CHECKOUT_STATUS_PENDING:
        db.close()
        return jsonify({"msg": "当前订单没有待审核的反结账申请"}), 400

    now = datetime.now()
    remind_until = now + timedelta(days=SETTLEMENT_REMIND_DAYS)
    cursor.execute(
        "UPDATE orders SET settlement_status=%s, payment_method=NULL, settlement_remind_until=%s, settlement_at=NULL, "
        "review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL, resubmitted_at=NULL, "
        "reverse_checkout_status=%s, reverse_checkout_reason=NULL, reverse_checkout_requested_by=NULL, "
        "reverse_checkout_requested_at=NULL, reverse_checkout_rejected_by=NULL, reverse_checkout_rejected_at=NULL "
        "WHERE id=%s",
        (
            SETTLEMENT_STATUS_UNSETTLED,
            remind_until.strftime("%Y-%m-%d %H:%M:%S"),
            REVIEW_STATUS_PENDING,
            REVERSE_CHECKOUT_STATUS_NONE,
            order_id,
        ),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "reverse checkout approved"})


@bp.route("/api/orders/<int:order_id>", methods=["DELETE"])
@auth_required()
def delete_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

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

    shipping_status = (order.get("shipping_status") or "").strip() or "未发货"
    if shipping_status == "已发货":
        db.close()
        return jsonify({"msg": "已发货订单不可删除"}), 400

    try:
        cursor.execute("DELETE FROM order_items WHERE order_id=%s", (order_id,))
        cursor.execute("DELETE FROM orders WHERE id=%s", (order_id,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    return jsonify({"msg": "order deleted"})


@bp.route("/api/orders/<int:order_id>/copy", methods=["POST"])
@auth_required()
def copy_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor_plain = db.cursor()
    cursor.execute("SELECT * FROM orders WHERE id=%s", (order_id,))
    source_order = cursor.fetchone()
    if not source_order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and source_order.get("clerk_id") != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403

    cursor.execute(
        "SELECT product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark "
        "FROM order_items WHERE order_id=%s ORDER BY id ASC",
        (order_id,),
    )
    source_items = cursor.fetchall()
    if not source_items:
        db.close()
        return jsonify({"msg": "source order items not found"}), 400

    new_order_date = datetime.now().date()
    settlement_status = normalize_settlement_status(source_order.get("settlement_status"))
    payment_method = normalize_payment_method(source_order.get("payment_method"), settlement_status)
    settlement_status, payment_method, settlement_remind_until, settlement_at = build_settlement_fields(
        None,
        {
            "settlement_status": settlement_status,
            "payment_method": payment_method,
        },
    )
    review_status = get_default_review_status_for_settlement(settlement_status)
    shipping_status = "未发货"
    shipping_time = None
    tracking_number = None
    clerk_id = current_user_id
    order_clerk = get_username_by_user_id(cursor_plain, clerk_id)
    salesperson = (source_order.get("salesperson") or "").strip() or None
    order_lock_acquired = False

    try:
        acquire_order_number_lock(cursor_plain, timeout_seconds=10)
        order_lock_acquired = True
        new_order_number = generate_order_number(cursor_plain, new_order_date)
        cursor_plain.execute(
            "INSERT INTO orders (order_number, customer_name, recipient_name, recipient_address, clerk_id, order_clerk, salesperson, order_date, "
            "shipping_status, shipping_time, tracking_number, shipping_fee, discount_amount, total_amount, payment_method, "
            "settlement_status, settlement_remind_until, settlement_at, review_status, reject_reason, rejected_by, rejected_at, resubmitted_at, remark) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                new_order_number,
                source_order.get("customer_name"),
                source_order.get("recipient_name"),
                source_order.get("recipient_address"),
                clerk_id,
                order_clerk,
                salesperson,
                new_order_date.strftime("%Y-%m-%d"),
                shipping_status,
                shipping_time,
                tracking_number,
                source_order.get("shipping_fee") or 0,
                source_order.get("discount_amount") or 0,
                source_order.get("total_amount") or 0,
                payment_method,
                settlement_status,
                settlement_remind_until.strftime("%Y-%m-%d %H:%M:%S") if settlement_remind_until else None,
                settlement_at.strftime("%Y-%m-%d %H:%M:%S") if settlement_at else None,
                review_status,
                None,
                None,
                None,
                None,
                source_order.get("remark"),
            ),
        )
        new_order_id = cursor_plain.lastrowid

        for item in source_items:
            sample_date = item.get("sample_date")
            sample_date_value = parse_order_date(sample_date).strftime("%Y-%m-%d") if sample_date else None
            cursor_plain.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, product_code, english_name, capacity, quantity, unit_price, amount, color, sample_date, remark) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    new_order_id,
                    item.get("product_id") or None,
                    normalize_item_text(item.get("product_name")),
                    normalize_item_text(item.get("product_code")),
                    normalize_item_text(item.get("english_name")),
                    normalize_item_text(item.get("capacity")),
                    item.get("quantity"),
                    item.get("unit_price") or 0,
                    item.get("amount") or 0,
                    (item.get("color") or "").strip() or None,
                    sample_date_value,
                    item.get("remark"),
                ),
            )

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

    return jsonify({"msg": "order copied", "order_id": new_order_id, "order_number": new_order_number})


@bp.route("/api/orders/review", methods=["GET"])
@auth_required()
def get_orders_for_review():
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    clerk_id = request.args.get("clerk_id", type=int)
    customer_name = (request.args.get("customer_name") or "").strip()
    order_number = (request.args.get("order_number") or "").strip()
    review_status = (request.args.get("review_status") or "").strip()
    rejected_only = request.args.get("rejected_only") in ("1", "true", "True")

    query = [
        "SELECT o.*, COALESCE(o.order_clerk, u.username) AS clerk_name, rb.username AS rejected_by_name",
        "FROM orders o",
        "LEFT JOIN users u ON u.id = o.clerk_id",
        "LEFT JOIN users rb ON rb.id = o.rejected_by",
        "WHERE o.settlement_status=%s",
    ]
    params = [SETTLEMENT_STATUS_UNSETTLED]

    if current_role != "admin":
        query.append("AND o.clerk_id=%s")
        params.append(current_user_id)
    elif clerk_id:
        query.append("AND o.clerk_id=%s")
        params.append(clerk_id)

    if customer_name:
        query.append("AND o.customer_name LIKE %s")
        params.append(f"%{customer_name}%")

    if order_number:
        query.append("AND o.order_number LIKE %s")
        params.append(f"%{order_number}%")

    if review_status:
        query.append("AND o.review_status=%s")
        params.append(review_status)

    if rejected_only:
        query.append("AND o.review_status=%s")
        params.append(REVIEW_STATUS_REJECTED)

    query.append("ORDER BY o.order_date DESC, o.id DESC")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute(" ".join(query), params)
    orders = [serialize_order_flags(order) for order in cursor.fetchall()]
    db.close()
    return jsonify(orders)


@bp.route("/api/orders/<int:order_id>/reject", methods=["POST"])
@auth_required(required_role="admin")
def reject_order(order_id):
    data = request.json or {}
    reason = (data.get("reason") or "").strip()
    if not reason:
        return jsonify({"msg": "驳回原因不能为空"}), 400

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, settlement_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可驳回"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=%s, rejected_by=%s, rejected_at=%s WHERE id=%s",
        (REVIEW_STATUS_REJECTED, reason, g.current_user.get("user_id"), now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order rejected"})


@bp.route("/api/orders/<int:order_id>/resubmit", methods=["POST"])
@auth_required()
def resubmit_order(order_id):
    current_user = g.current_user
    current_role = normalize_role(current_user.get("role"))
    current_user_id = current_user.get("user_id")

    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, clerk_id, settlement_status, review_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if current_role != "admin" and order["clerk_id"] != current_user_id:
        db.close()
        return jsonify({"msg": "forbidden"}), 403
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可重新提交"}), 400
    if normalize_review_status(order.get("review_status")) != REVIEW_STATUS_REJECTED:
        db.close()
        return jsonify({"msg": "仅已驳回订单可重新提交"}), 400

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL, resubmitted_at=%s WHERE id=%s",
        (REVIEW_STATUS_PENDING, now, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order resubmitted"})


@bp.route("/api/orders/<int:order_id>/approve", methods=["POST"])
@auth_required(required_role="admin")
def approve_order(order_id):
    db = get_db()
    cursor = db.cursor(MySQLdb.cursors.DictCursor)
    cursor.execute("SELECT id, settlement_status FROM orders WHERE id=%s", (order_id,))
    order = cursor.fetchone()
    if not order:
        db.close()
        return jsonify({"msg": "order not found"}), 404
    if normalize_settlement_status(order.get("settlement_status")) != SETTLEMENT_STATUS_UNSETTLED:
        db.close()
        return jsonify({"msg": "仅未结账订单可审核通过"}), 400

    cursor.execute(
        "UPDATE orders SET review_status=%s, reject_reason=NULL, rejected_by=NULL, rejected_at=NULL WHERE id=%s",
        (REVIEW_STATUS_APPROVED, order_id),
    )
    db.commit()
    db.close()
    return jsonify({"msg": "order approved"})
