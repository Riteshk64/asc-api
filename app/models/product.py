from app.extensions import db
from datetime import datetime

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    product_code = db.Column(db.String(50), unique=True, nullable=False) # SKU
    unit = db.Column(db.String(20), nullable=True)
    category = db.Column(db.String(50), nullable=True)
    
    current_stock = db.Column(db.Float, default=0.0)
    
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "sku": self.product_code,
            "unit": self.unit, "qty": self.current_stock,
            "is_active": self.is_active
        }