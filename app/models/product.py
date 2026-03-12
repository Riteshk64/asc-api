from app.extensions import db
from datetime import datetime

class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    product_code = db.Column(db.String(50), nullable=False) 
    current_stock = db.Column(db.Float, default=0.0)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    min_stock = db.Column(db.Float, default=10.0)
    max_stock = db.Column(db.Float, default=100.0)
    is_active = db.Column(db.Boolean, default=True)
    unit = db.Column(db.String(20), default='pcs')
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    sub_category_id = db.Column(db.Integer, db.ForeignKey('sub_categories.id'), nullable=True)

    def to_dict(self):
        return {
            "id": self.id, 
            "name": self.name, 
            "sku": self.product_code,  # Kept only sku
            "qty": self.current_stock,
            "is_active": self.is_active, 
            "min_stock": self.min_stock,  
            "max_stock": self.max_stock, 
            "unit": self.unit, 
            "category_id": self.category_id,
            "category_name": self.category_rel.name if self.category_rel else "OTHER",
            "sub_category_id": self.sub_category_id,
            "sub_category_name": self.sub_category_rel.name if self.sub_category_rel else "GENERAL",
            "department_id": self.department_id
        }