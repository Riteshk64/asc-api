from app.extensions import db
from datetime import datetime

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    
    ordered_qty = db.Column(db.Float, nullable=False)
    dispatched_qty = db.Column(db.Float, default=0.0) 
    
    product = db.relationship('Product', lazy='joined')

    def to_dict(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "product_name": self.product.name if self.product else "Unknown",
            "sku": self.product.product_code if self.product else "",
            "ordered_qty": self.ordered_qty,
            "dispatched_qty": self.dispatched_qty,
            "pending_qty": self.ordered_qty - self.dispatched_qty
        }

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # PENDING, PARTIALLY_DISPATCHED, FULFILLED, CANCELLED
    status = db.Column(db.String(30), default='PENDING') 
    
    # 👇 Logistics Tracking for Admins
    challan_number = db.Column(db.String(100), nullable=True)
    lr_number = db.Column(db.String(100), nullable=True) # Lorry Receipt
    transport_details = db.Column(db.Text, nullable=True) # "VRL Logistics, Truck No..."
    
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dispatched_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', lazy='joined')
    items = db.relationship('OrderItem', backref='order', lazy='joined', cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "client_name": f"{self.user.first_name} {self.user.last_name}".strip() if self.user else "Unknown",
            "client_phone": self.user.phoneno if self.user else "",
            "status": self.status,
            "challan_number": self.challan_number,
            "lr_number": self.lr_number,
            "transport_details": self.transport_details,
            "notes": self.notes,
            "created_at": self.created_at.strftime('%Y-%m-%d'),
            "dispatched_at": self.dispatched_at.strftime('%Y-%m-%d') if self.dispatched_at else None,
            "items": [item.to_dict() for item in self.items]
        }