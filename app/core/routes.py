from flask import Blueprint

core = Blueprint('core',__name__,url_prefix='/core')

@core.route('/test')
def test():
    return 'core test'