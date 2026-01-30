from app.extensions import db
from datetime import datetime

class Transaction(db.Model):
    __tablename__ = 'transactions'
    id = db.Column(db.Integer, primary_key=True)
    
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # Linked Entities
    supplier_id = db.Column(db.Integer, db.ForeignKey('suppliers.id'), nullable=True)
    contractor_id = db.Column(db.Integer, db.ForeignKey('contractors.id'), nullable=True)
    
    type = db.Column(db.String(10), nullable=False) # IN, OUT
    quantity = db.Column(db.Float, nullable=False)
    
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    
    # For Recycle Bin
    is_active = db.Column(db.Boolean, default=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    product = db.relationship('Product', backref='transactions')
    supplier = db.relationship('Supplier')
    contractor = db.relationship('Contractor')
    user = db.relationship('User')

    def to_dict(self):
        entity = "Adjustment"
        if self.supplier: entity = f"Supplier: {self.supplier.name}"
        elif self.contractor: entity = f"Contractor: {self.contractor.name}"

        return {
            "id": self.id, 
            "product": self.product.name if self.product else "Unknown",
            "sku": self.product.product_code if self.product else "",
            "type": self.type, 
            "qty": self.quantity,
            "entity": entity, 
            "date": self.created_at.strftime('%Y-%m-%d'),
            "is_active": self.is_active,
            
            # --- NEW ADDITIONS FOR ROBUST FILTERING ---
            "contractor_id": self.contractor_id, 
            "supplier_id": self.supplier_id
        }