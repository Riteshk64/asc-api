from app.extensions import db

class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # 👆 Higher numbers go lower in the PDF
    display_order = db.Column(db.Integer, default=0) 
    
    products = db.relationship('Product', backref='category_rel', lazy=True)
    match_codes = db.Column(db.String(100), nullable=True) # e.g., "BK,BLK"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "display_order": self.display_order,
            "match_codes": self.match_codes # 👈 Add this
        }

    # def to_dict(self):
    #     return {
    #         "id": self.id,
    #         "name": self.name,
    #         "display_order": self.display_order
    #     }