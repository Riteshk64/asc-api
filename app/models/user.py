from app.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False) # Login ID
    otp = db.Column(db.String(100), nullable=True) # Bcrypt hash
    role = db.Column(db.String(20), default='USER') 
    
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "name": self.name, "phone": self.phone,
            "role": self.role, "department_id": self.department_id,
            "is_active": self.is_active
        }