# # app/models/order.py

# from app.extensions import db
# from datetime import datetime, date, timedelta


# class Order(db.Model):
#     __tablename__ = 'orders'

#     id = db.Column(db.Integer, primary_key=True)
#     contractor_id = db.Column(
#         db.Integer,
#         db.ForeignKey('contractors.id'),
#         nullable=False
#     )
#     department_id = db.Column(
#         db.Integer,
#         db.ForeignKey('departments.id'),
#         nullable=False
#     )

#     status = db.Column(db.String(30), default='PENDING')  # PENDING, PARTIAL, FULFILLED
#     notes = db.Column(db.Text, nullable=True)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)
#     order_date = db.Column(db.Date, default=date.today)
#     required_date = db.Column(db.Date, nullable=True)
#     edit_counter = db.Column(db.Integer, default=0)
#     is_active = db.Column(db.Boolean, default=True)
#     challan_number = db.Column(db.String(50), nullable=True)

#     # Relationships
#     contractor = db.relationship('Contractor', lazy='joined')
#     items = db.relationship(
#         'OrderItem',
#         backref='order',
#         lazy='joined',
#         cascade='all, delete-orphan'
#     )

#     # ==========================================================
#     # THIS METHOD IS REQUIRED
#     # Your route calls:
#     # return jsonify([o.to_dict() for o in orders]), 200
#     # ==========================================================
#     def to_dict(self):
#         is_overdue = False

#         # 👇 FIX: Changed from == 'PENDING' to 'in' list
#         if self.status in ['PENDING', 'PARTIAL']:
#             # Priority 1: Use required_date if supplied
#             if self.required_date and date.today() > self.required_date:
#                 is_overdue = True

#             # Priority 2: Fallback to 30 days from order_date
#             elif (
#                 not self.required_date
#                 and self.order_date
#                 and date.today() > self.order_date + timedelta(days=30)
#             ):
#                 is_overdue = True

#         return {
#             "id": self.id,
#             "contractor_id": self.contractor_id,
#             "contractor_name": (
#                 self.contractor.name if self.contractor else "Unknown"
#             ),
#             "department_id": self.department_id,
#             "status": self.status,
#             "notes": self.notes,
#             "created_at": (
#                 self.created_at.strftime('%Y-%m-%d')
#                 if self.created_at else None
#             ),
#             "order_date": (
#                 self.order_date.strftime('%Y-%m-%d')
#                 if self.order_date else None
#             ),
#             "required_date": (
#                 self.required_date.strftime('%Y-%m-%d')
#                 if self.required_date else None
#             ),
#             "challan_number": self.challan_number,
#             "edit_counter": self.edit_counter,
#             "is_active": self.is_active,
#             "is_overdue": is_overdue,
#             "items": [item.to_dict() for item in self.items]
#         }


# class OrderItem(db.Model):
#     __tablename__ = 'order_items'

#     id = db.Column(db.Integer, primary_key=True)
#     order_id = db.Column(
#         db.Integer,
#         db.ForeignKey('orders.id'),
#         nullable=False
#     )
#     product_id = db.Column(
#         db.Integer,
#         db.ForeignKey('products.id'),
#         nullable=False
#     )

#     quantity = db.Column(db.Float, nullable=False)  # Stored in PCS
#     dispatched_qty = db.Column(db.Float, default=0.0)

#     product = db.relationship('Product', lazy='joined')

#     def to_dict(self):
#         return {
#             "id": self.id,
#             "product_id": self.product_id,
#             "product_name": (
#                 self.product.name if self.product else "Unknown"
#             ),
#             "sku": (
#                 self.product.product_code if self.product else ""
#             ),
#             "unit": (
#                 self.product.unit if self.product else "pcs"
#             ),
#             "pcs_per_box": (
#                 self.product.pcs_per_box if self.product else 0
#             ),
#             "ordered_qty": self.quantity,
#             "quantity": self.quantity,   # compatibility with older frontend code
#             "dispatched_qty": self.dispatched_qty,
#             "pending_qty": self.quantity - self.dispatched_qty
#         }

# app/models/order.py

from app.extensions import db
from datetime import datetime, date, timedelta

class Order(db.Model):
    __tablename__ = 'orders'

    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(
        db.Integer,
        db.ForeignKey('contractors.id'),
        nullable=False
    )
    department_id = db.Column(
        db.Integer,
        db.ForeignKey('departments.id'),
        nullable=False
    )

    status = db.Column(db.String(30), default='PENDING')  # PENDING, PARTIAL, FULFILLED
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order_date = db.Column(db.Date, default=date.today)
    required_date = db.Column(db.Date, nullable=True)
    edit_counter = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    challan_number = db.Column(db.String(50), nullable=True)

    # Relationships
    contractor = db.relationship('Contractor', lazy='joined')
    items = db.relationship(
        'OrderItem',
        backref='order',
        lazy='joined',
        cascade='all, delete-orphan'
    )

    def to_dict(self):
        is_overdue = False

        if self.status in ['PENDING', 'PARTIAL']:
            if self.required_date and date.today() > self.required_date:
                is_overdue = True
            elif (
                not self.required_date
                and self.order_date
                and date.today() > self.order_date + timedelta(days=30)
            ):
                is_overdue = True

        # 👇 THE FIX: Fetch the actual dispatch history (Transactions) for this order
        from app.models.transaction import Transaction
        
        dispatches = Transaction.query.filter_by(
            order_id=self.id, 
            type='out', 
            is_active=True
        ).order_by(Transaction.created_at.desc()).all()

        dispatch_history = []
        for d in dispatches:
            dispatch_history.append({
                "transaction_id": d.id,
                "challan_id": d.challan_id or "N/A",
                "product_name": d.product.name if d.product else "Unknown",
                "sku": d.product.product_code if d.product else "",
                "qty": d.quantity,
                "date": d.created_at.strftime('%Y-%m-%d') if d.created_at else None
            })

        return {
            "id": self.id,
            "contractor_id": self.contractor_id,
            "contractor_name": (
                self.contractor.name if self.contractor else "Unknown"
            ),
            "department_id": self.department_id,
            "status": self.status,
            "notes": self.notes,
            "created_at": (
                self.created_at.strftime('%Y-%m-%d')
                if self.created_at else None
            ),
            "order_date": (
                self.order_date.strftime('%Y-%m-%d')
                if self.order_date else None
            ),
            "required_date": (
                self.required_date.strftime('%Y-%m-%d')
                if self.required_date else None
            ),
            "challan_number": self.challan_number,
            "edit_counter": self.edit_counter,
            "is_active": self.is_active,
            "is_overdue": is_overdue,
            "items": [item.to_dict() for item in self.items],
            "dispatch_history": dispatch_history # 👈 Attached to the JSON!
        }


class OrderItem(db.Model):
    __tablename__ = 'order_items'

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(
        db.Integer,
        db.ForeignKey('orders.id'),
        nullable=False
    )
    product_id = db.Column(
        db.Integer,
        db.ForeignKey('products.id'),
        nullable=False
    )

    quantity = db.Column(db.Float, nullable=False) 
    dispatched_qty = db.Column(db.Float, default=0.0)

    product = db.relationship('Product', lazy='joined')

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": (
                self.product.name if self.product else "Unknown"
            ),
            "sku": (
                self.product.product_code if self.product else ""
            ),
            "unit": (
                self.product.unit if self.product else "pcs"
            ),
            "pcs_per_box": (
                self.product.pcs_per_box if self.product else 0
            ),
            "ordered_qty": self.quantity,
            "quantity": self.quantity,  
            "dispatched_qty": self.dispatched_qty,
            "pending_qty": self.quantity - self.dispatched_qty
        }