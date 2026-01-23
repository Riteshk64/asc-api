from app.extensions import db

class Contractor(db.Model):
    __tablename__ = "contractors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
