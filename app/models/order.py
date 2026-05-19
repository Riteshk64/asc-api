from app.extensions import db
from datetime import datetime
from datetime import date, timedelta

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey('contractors.id'), nullable=False) 
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    
    status = db.Column(db.String(30), default='PENDING') # PENDING, PARTIAL, FULFILLED
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    order_date = db.Column(db.Date, default=date.today)
    edit_counter = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    challan_number = db.Column(db.String(50), nullable=True)

    # Relationships
    contractor = db.relationship('Contractor', lazy='joined')
    items = db.relationship('OrderItem', backref='order', lazy='joined', cascade="all, delete-orphan")

    def to_dict(self):
        is_overdue = False
        if self.status == 'PENDING' and self.order_date:
            if date.today() > self.order_date + timedelta(days=30):
                is_overdue = True

        return {
            "id": self.id,
            "contractor_id": self.contractor_id,
            "contractor_name": self.contractor.name if self.contractor else "Unknown",
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at.strftime('%Y-%m-%d'),
            "items": [item.to_dict() for item in self.items],
            "challan_number": self.challan_number,
            "order_date": self.order_date.strftime('%Y-%m-%d') if self.order_date else self.created_at.strftime('%Y-%m-%d'),
            "edit_counter": self.edit_counter,
            "is_overdue": is_overdue,
            "items": [item.to_dict() for item in self.items]
            
        }

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    
    quantity = db.Column(db.Float, nullable=False) # Stored purely in PCS
    dispatched_qty = db.Column(db.Float, default=0.0)
    
    product = db.relationship('Product', lazy='joined')


    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "Unknown",
            "sku": self.product.product_code if self.product else "",
            "unit": self.product.unit if self.product else "pcs",
            "pcs_per_box": self.product.pcs_per_box if self.product else 0,
            "ordered_qty": self.quantity,
            "dispatched_qty": self.dispatched_qty,
            "pending_qty": self.quantity - self.dispatched_qty
        }