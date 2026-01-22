from flask import Blueprint

auth = Blueprint('auth',__name__,url_prefix='/auth')

@auth.route('/test')
def test():
    return 'auth test'