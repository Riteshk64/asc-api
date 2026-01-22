from flask import Blueprint

analytics = Blueprint('analytics',__name__,url_prefix='/analytics')

@analytics.route('/test')
def test():
    return 'analytics test'