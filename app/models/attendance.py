from app.extensions import db
from datetime import datetime


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    department_id = db.Column(
        db.Integer,
        db.ForeignKey("departments.id"),
        nullable=True,
        index=True
    )

    date = db.Column(db.Date, nullable=False, index=True)

    status = db.Column(
        db.String(20),
        default="PRESENT"
    )  # PRESENT / ABSENT / HALF_DAY

    # Hours
    hours_worked = db.Column(db.Float, default=0.0)
    regular_hours = db.Column(db.Float, default=0.0)
    overtime_hours = db.Column(db.Float, default=0.0)

    # Payroll snapshot (important for history)
    logged_pay_type = db.Column(db.String(20), nullable=False)
    hourly_rate_at_time = db.Column(db.Float, default=0.0)
    overtime_rate_at_time = db.Column(db.Float, default=0.0)

    # Earnings
    daily_base_earnings = db.Column(db.Float, default=0.0)
    daily_overtime_earnings = db.Column(db.Float, default=0.0)
    total_daily_earnings = db.Column(db.Float, default=0.0)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    user = db.relationship(
        "User",
        back_populates="attendance_records",
        foreign_keys=[user_id]
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "date",
            name="unique_user_attendance_per_day"
        ),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "date": self.date.strftime("%Y-%m-%d"),
            "status": self.status,
            "hours_worked": self.hours_worked,
            "regular_hours": self.regular_hours,
            "overtime_hours": self.overtime_hours,
            "total_daily_earnings": self.total_daily_earnings
        }