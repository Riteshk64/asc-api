from app.extensions import db

class Departments(db.Model):
    __tablename__ = "departments"
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
