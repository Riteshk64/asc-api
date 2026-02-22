from sqlalchemy import func, desc
from app.extensions import db
from app.models.transaction import Transaction
from app.models.product import Product

# -----------------------------
# General activity frequency
# -----------------------------
def get_frequency_data(filters):
    """
    How many times was each product touched (all transaction types)
    OPTIMIZED: Use direct SQL aggregation instead of loading full objects
    """
    results = db.session.query(
        Product.name,
        func.count(Transaction.id).label('count')
    ).join(Product).filter(*filters).group_by(Product.id, Product.name).order_by(desc('count')).limit(10).all()

    return [{"name": r.name, "count": r.count} for r in results]


# -----------------------------
# Pie Chart: OUT volume
# OPTIMIZED: Use indexed type column
# -----------------------------
def get_top_issued_volume(filters):
    out_filters = filters + [Transaction.type == 'out']

    results = db.session.query(
        Product.name,
        func.sum(Transaction.quantity).label('qty')
    ).join(Product).filter(*out_filters).group_by(Product.id, Product.name).order_by(desc('qty')).limit(5).all()

    return [{"name": r.name, "qty": float(r.qty or 0)} for r in results]


# -----------------------------
# Table: Frequent OUT pressure
# OPTIMIZED: Use indexed type column
# -----------------------------
def get_consistent_pressure(filters):
    out_filters = filters + [Transaction.type == 'out']

    results = db.session.query(
        Product.name,
        func.count(Transaction.id).label('hits')
    ).join(Product).filter(*out_filters).group_by(Product.id, Product.name).order_by(desc('hits')).limit(5).all()

    return [{"name": r.name, "hits": r.hits} for r in results]


# -----------------------------
# Bar Chart: Stock IN volume
# OPTIMIZED: Use indexed type column
# -----------------------------
def get_top_stocked_in(filters):
    in_filters = filters + [Transaction.type == 'in']

    results = db.session.query(
        Product.name,
        func.sum(Transaction.quantity).label('qty')
    ).join(Product).filter(*in_filters).group_by(Product.id, Product.name).order_by(desc('qty')).limit(10).all()

    return [{"name": r.name, "qty": float(r.qty or 0)} for r in results]
