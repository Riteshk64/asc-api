from app.extensions import db
from app.models.product import Product
from app.models.transaction import Transaction
from sqlalchemy import func, desc

def get_frequency_data(filters):
    """How many times was a product touched?"""
    results = db.session.query(
        Product.name, func.count(Transaction.id).label('c')
    ).join(Product).filter(*filters).group_by(Product.name).order_by(desc('c')).limit(10).all()
    
    return [{"name": r[0], "count": r[1]} for r in results]

def get_top_issued_volume(filters):
    """Total Quantity sent out (Pie Chart)"""
    # Append 'OUT' filter specifically
    out_filters = filters + [Transaction.type == 'out']
    
    results = db.session.query(
        Product.name, func.sum(Transaction.quantity).label('q')
    ).join(Product).filter(*out_filters).group_by(Product.name).order_by(desc('q')).limit(5).all()
    
    return [{"name": r[0], "qty": r[1]} for r in results]

def get_consistent_pressure(filters):
    """Most frequent issuance events"""
    out_filters = filters + [Transaction.type == 'out']
    
    results = db.session.query(
        Product.name, func.count(Transaction.id).label('hits')
    ).join(Product).filter(*out_filters).group_by(Product.name).order_by(desc('hits')).limit(5).all()
    
    return [{"name": r[0], "hits": r[1]} for r in results]