from flask import Blueprint

bp = Blueprint('users', __name__)

@bp.get('/users')
def list_users():
    return {'data': []}
