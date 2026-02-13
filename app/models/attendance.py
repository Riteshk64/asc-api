from app.extensions import db
from datetime import datetime

class Attendance(db.Model):
    __tablename__ = 'attendance'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    

    hours_worked = db.Column(db.Float, default=0.0)
    

    regular_hours = db.Column(db.Float, default=0.0)
    

    hourly_rate_at_time = db.Column(db.Float, nullable=False)
    daily_earnings = db.Column(db.Float, default=0.0)
    

    status = db.Column(db.String(20), default='Present') 
    upload_batch_id = db.Column(db.String(100), index=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "date": self.date.strftime('%Y-%m-%d'),
            "hours_worked": self.hours_worked,
            "regular_hours": self.regular_hours,
            "daily_earnings": self.daily_earnings,
            "status": self.status
        }

    @staticmethod
    def calculate_pay(user, total_hours):
        """
        Helper method to calculate OT and earnings before saving.
        """
        reg_hours = min(total_hours, user.daily_required_hours)
        
 
        hourly_rate = (user.monthly_salary / 26) / user.daily_required_hours
        return {
            "regular_hours": reg_hours,
            "hourly_rate": hourly_rate,
        }