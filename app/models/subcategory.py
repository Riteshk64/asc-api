from app.extensions import db


class SubCategory(db.Model):
    __tablename__ = 'sub_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    
    # 🚨 ADD THIS LINE 🚨
    display_order = db.Column(db.Integer, default=0) 
    
    products = db.relationship('Product', backref='sub_category_rel', lazy=True)

    match_rule = db.Column(db.String(50), default='first_word') # 'first_word', 'last_word', etc.

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_order": self.display_order,
            "match_rule": self.match_rule # 👈 Add this
        }