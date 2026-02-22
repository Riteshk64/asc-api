from sqlalchemy import func, desc
from app.extensions import db
from app.models.transaction import Transaction
from app.models.supplier import Supplier
from app.models.contractor import Contractor

# -----------------------------
# Top Suppliers (IN)
# OPTIMIZED: Use indexed columns
# -----------------------------
def get_top_suppliers(filters):
    in_filters = filters + [
        Transaction.type == 'in',
        Transaction.supplier_id != None
    ]

    results = db.session.query(
        Supplier.name,
        func.sum(Transaction.quantity).label('qty')
    ).join(Transaction, Transaction.supplier_id == Supplier.id).filter(*in_filters).group_by(Supplier.id, Supplier.name).order_by(desc('qty')).limit(5).all()

    return [{"name": r.name, "qty": float(r.qty or 0)} for r in results]


# -----------------------------
# Top Contractors (OUT)
# OPTIMIZED: Use indexed columns
# -----------------------------
def get_top_contractors(filters):
    out_filters = filters + [
        Transaction.type == 'out',
        Transaction.contractor_id != None
    ]

    results = db.session.query(
        Contractor.name,
        func.sum(Transaction.quantity).label('qty')
    ).join(Transaction, Transaction.contractor_id == Contractor.id).filter(*out_filters).group_by(Contractor.id, Contractor.name).order_by(desc('qty')).limit(5).all()

    return [{"name": r.name, "qty": float(r.qty or 0)} for r in results]
