from datetime import date, datetime, timedelta

from constants import (
    ORDER_NUMBER_LOCK_NAME,
    PAYMENT_METHODS,
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


def parse_order_date(value):
    if not value:
        return datetime.now().date()

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return datetime.now().date()

        for pattern in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(normalized, pattern).date()
            except ValueError:
                continue

        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).date()

    raise ValueError("invalid_order_date")


def normalize_item_text(value):
    return (value or "").strip() or None


def normalize_settlement_status(value):
    if value == SETTLEMENT_STATUS_UNSETTLED:
        return SETTLEMENT_STATUS_UNSETTLED
    return SETTLEMENT_STATUS_SETTLED


def normalize_payment_method(value, settlement_status):
    method = (value or "").strip()
    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        return None
    if method and method in PAYMENT_METHODS:
        return method
    return "支付宝"


def normalize_review_status(value):
    if value == "待审核":
        return REVIEW_STATUS_PENDING
    if value in (REVIEW_STATUS_PENDING, REVIEW_STATUS_REJECTED, REVIEW_STATUS_APPROVED):
        return value
    return REVIEW_STATUS_APPROVED


def normalize_reverse_checkout_status(value):
    if value in (REVERSE_CHECKOUT_STATUS_PENDING, REVERSE_CHECKOUT_STATUS_REJECTED):
        return value
    return REVERSE_CHECKOUT_STATUS_NONE


def build_settlement_fields(existing_order, data):
    settlement_status = normalize_settlement_status(data.get("settlement_status") or (existing_order or {}).get("settlement_status"))
    payment_method = normalize_payment_method(data.get("payment_method"), settlement_status)
    existing_status = normalize_settlement_status((existing_order or {}).get("settlement_status"))
    existing_remind_until = (existing_order or {}).get("settlement_remind_until")
    existing_settlement_at = (existing_order or {}).get("settlement_at")
    now = datetime.now()

    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        settlement_at = None
        settlement_remind_until = existing_remind_until
        if existing_status != SETTLEMENT_STATUS_UNSETTLED or not settlement_remind_until:
            settlement_remind_until = now + timedelta(days=SETTLEMENT_REMIND_DAYS)
    else:
        settlement_remind_until = None
        settlement_at = existing_settlement_at if existing_status == SETTLEMENT_STATUS_SETTLED else now

    return settlement_status, payment_method, settlement_remind_until, settlement_at


def get_default_review_status_for_settlement(settlement_status):
    if settlement_status == SETTLEMENT_STATUS_UNSETTLED:
        return REVIEW_STATUS_PENDING
    return REVIEW_STATUS_APPROVED


def serialize_order_flags(order_row):
    settlement_status = normalize_settlement_status(order_row.get("settlement_status"))
    remind_until = order_row.get("settlement_remind_until")
    remind_active = bool(
        settlement_status == SETTLEMENT_STATUS_UNSETTLED
        and remind_until
        and remind_until >= datetime.now()
    )
    order_row["settlement_status"] = settlement_status
    order_row["need_settlement_remind"] = remind_active
    order_row["settlement_remind_days_left"] = (
        max(0, (remind_until - datetime.now()).days + (1 if (remind_until - datetime.now()).seconds > 0 else 0))
        if remind_active else 0
    )
    order_row["review_status"] = normalize_review_status(order_row.get("review_status"))
    order_row["reverse_checkout_status"] = normalize_reverse_checkout_status(order_row.get("reverse_checkout_status"))
    return order_row


def _get_first_column(row):
    if row is None:
        return None
    if isinstance(row, (list, tuple)):
        return row[0] if row else None
    if isinstance(row, dict):
        for _, value in row.items():
            return value
        return None
    return row


def generate_order_number(cursor, order_date):
    prefix = order_date.strftime("%Y%m%d")
    cursor.execute(
        "SELECT order_number FROM orders WHERE order_number LIKE %s ORDER BY order_number DESC LIMIT 1",
        (f"{prefix}%",),
    )
    latest = cursor.fetchone()
    last_number = _get_first_column(latest) if latest else None
    next_sequence = int(last_number[-4:]) + 1 if last_number else 1
    return f"{prefix}{next_sequence:04d}"


def acquire_order_number_lock(cursor, timeout_seconds=10):
    cursor.execute("SELECT GET_LOCK(%s, %s)", (ORDER_NUMBER_LOCK_NAME, timeout_seconds))
    result = cursor.fetchone()
    lock_status = _get_first_column(result)
    if lock_status != 1:
        raise RuntimeError("order_number_lock_timeout")


def release_order_number_lock(cursor):
    try:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (ORDER_NUMBER_LOCK_NAME,))
    except Exception:
        pass
