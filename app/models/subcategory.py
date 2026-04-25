from app.extensions import db


class SubCategory(db.Model):
    __tablename__ = 'sub_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    
    # 🚨 ADD THIS LINE 🚨
    display_order = db.Column(db.Integer, default=0) 
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    products = db.relationship('Product', backref='sub_category_rel', lazy=True)
    is_active = db.Column(db.Boolean, default=True)


    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_order": self.display_order,
            "is_active": self.is_active
        }