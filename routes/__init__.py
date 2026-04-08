from routes.auth import bp as auth_bp
from routes.drafts import bp as drafts_bp
from routes.orders import bp as orders_bp
from routes.products import bp as products_bp
from routes.salespersons import bp as salespersons_bp
from routes.users import bp as users_bp


ALL_BLUEPRINTS = [
    auth_bp,
    users_bp,
    salespersons_bp,
    products_bp,
    drafts_bp,
    orders_bp,
]
