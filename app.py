import os

from flask import Flask
from flask_cors import CORS

from config import MYSQL_DB, MYSQL_HOST, MYSQL_PORT, MYSQL_USER, SECRET_KEY
from routes import ALL_BLUEPRINTS
from schema import (
    ensure_order_draft_schema,
    ensure_order_item_detail_schema,
    ensure_order_items_color_schema,
    ensure_order_recipient_schema,
    ensure_order_settlement_schema,
    ensure_order_staff_schema,
    ensure_salesperson_schema,
    run_schema_checks,
)


def create_app():
    app = Flask(__name__)
    CORS(app)
    app.config["SECRET_KEY"] = SECRET_KEY

    for blueprint in ALL_BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app


app = create_app()


if __name__ == "__main__":
    print(f"[DB] host={MYSQL_HOST} port={MYSQL_PORT} db={MYSQL_DB} user={MYSQL_USER}")
    run_schema_checks()
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
