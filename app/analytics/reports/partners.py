from app.extensions import db
from app.models.supplier import Supplier
from app.models.transaction import Transaction
from sqlalchemy import func, desc

def get_top_suppliers(filters):
    in_filters = filters + [Transaction.type == 'in', Transaction.supplier_id != None]
    
    results = db.session.query(
        Supplier.name, func.sum(Transaction.quantity).label('q')
    ).join(Transaction).filter(*in_filters).group_by(Supplier.name).order_by(desc('q')).limit(5).all()
    
    return [{"name": r[0], "qty": r[1]} for r in results]