# Assuming db is imported at the top: from app.extensions import db
from datetime import datetime
from app.extensions import db

class SupplierProduct(db.Model):
    __tablename__ = 'supplier_products'
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    
    # Optional relationships to make querying easier later
    supplier = db.relationship('Supplier', backref=db.backref('assigned_products', cascade='all, delete-orphan'))
    product = db.relationship('Product', backref=db.backref('assigned_suppliers', cascade='all, delete-orphan'))

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # The Supplier's User ID
    
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "is_read": self.is_read,
            "created_at": self.created_at.strftime('%Y-%m-%d %H:%M')
        }