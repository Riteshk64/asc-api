from app.extensions import db

class CategorySubOrder(db.Model):
    __tablename__ = 'category_sub_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id', ondelete='CASCADE'), nullable=False)
    sub_category_id = db.Column(db.Integer, db.ForeignKey('sub_categories.id', ondelete='CASCADE'), nullable=False)
    display_order = db.Column(db.Integer, default=99)

    
    def __repr__(self):
        return f"<CategorySubOrder(Cat ID: {self.category_id}, Sub ID: {self.sub_category_id}, Order: {self.display_order})>"