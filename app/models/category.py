# from app.extensions import db

# class Category(db.Model):
#     __tablename__ = 'categories'
#     id = db.Column(db.Integer, primary_key=True)
#     name = db.Column(db.String(50), unique=True, nullable=False)
#     display_order = db.Column(db.Integer, default=0) 
#     department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
#     products = db.relationship('Product', backref='category_rel', lazy=True)
#     is_active = db.Column(db.Boolean, default=True)

#     def to_dict(self):
#         return {
#             "id": self.id,
#             "name": self.name,
#             "display_order": self.display_order,
#             "is_active": self.is_active
#         }

#     # def to_dict(self):
#     #     return {
#     #         "id": self.id,
#     #         "name": self.name,
#     #         "display_order": self.display_order
#     #     }


from app.extensions import db

class Category(db.Model):
    __tablename__ = 'categories'
    
    # 👇 ADD THIS CONSTRAINT
    __table_args__ = (
        db.UniqueConstraint('name', 'department_id', name='uix_cat_name_dept'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # 👇 REMOVE unique=True here
    name = db.Column(db.String(50), nullable=False)
    
    display_order = db.Column(db.Integer, default=0) 
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    products = db.relationship('Product', backref='category_rel', lazy=True)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_order": self.display_order,
            "is_active": self.is_active
        }