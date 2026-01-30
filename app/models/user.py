from app.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phoneno = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False)  # ADMIN / USER

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=True
    )
