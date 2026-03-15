from flask import Blueprint

bp = Blueprint('orders', __name__)

@bp.get('/orders')
def list_orders():
    return {'data': []}
