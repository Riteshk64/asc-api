from app.extensions import db

class ActivityLog(db.Model):
    __tablename__ = "activity_logs"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False
    )

    action = db.Column(db.String(50), nullable=False)
    transaction_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
