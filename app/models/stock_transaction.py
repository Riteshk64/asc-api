from app.extensions import db

class StockTransaction(db.Model):
    __tablename__ = "stock_transactions"

    id = db.Column(db.Integer, primary_key=True)

    product_id = db.Column(
        db.Integer,
        db.ForeignKey("products.id"),
        nullable=False
    )

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=False
    )

    type = db.Column(db.String(10), nullable=False)  # IN / OUT
    quantity = db.Column(db.Float, nullable=False)

    supplier_id = db.Column(
        db.Integer,
        db.ForeignKey("suppliers.id"),
        nullable=True
    )

    contractor_id = db.Column(
        db.Integer,
        db.ForeignKey("contractors.id"),
        nullable=True
    )

    created_by = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    created_at = db.Column(db.DateTime, server_default=db.func.now())
