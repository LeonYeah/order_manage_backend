from app import (
    app,
    ensure_order_draft_schema,
    ensure_order_item_detail_schema,
    ensure_order_items_color_schema,
    ensure_order_recipient_schema,
    ensure_salesperson_schema,
    ensure_order_settlement_schema,
    ensure_order_staff_schema,
)


ensure_order_settlement_schema()
ensure_order_recipient_schema()
ensure_order_items_color_schema()
ensure_order_item_detail_schema()
ensure_order_staff_schema()
ensure_order_draft_schema()
ensure_salesperson_schema()
