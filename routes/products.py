from flask import Blueprint

bp = Blueprint('products', __name__)

@bp.get('/products')
def list_products():
    return {'data': []}
