# # from app.extensions import db
# # from datetime import datetime

# # class User(db.Model):
# #     __tablename__ = 'users'
# #     id = db.Column(db.Integer, primary_key=True)
# #     first_name = db.Column(db.String(100), nullable=False)
# #     last_name = db.Column(db.String(100), nullable=False)
# #     phoneno = db.Column(db.String(20), unique=True, nullable=False)
# #     role = db.Column(db.String(20), nullable=False)  

# #     department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
# #     is_active = db.Column(db.Boolean, default=True)
# #     created_at = db.Column(db.DateTime, default=datetime.utcnow)
# #     attendance_id = db.Column(db.String(50), unique=True, nullable=True)
# #     monthly_salary = db.Column(db.Float, default=0.0)
# #     daily_required_hours = db.Column(db.Float, default=8.0)

# #     def to_dict(self):
# #         return {
# #             "id": self.id, "first_name": self.first_name, "last_name": self.last_name, "phone": self.phoneno,
# #             "role": self.role, "department_id": self.department_id,
# #             "is_active": self.is_active
# #         }

# from app.extensions import db
# from datetime import datetime

# class User(db.Model):
#     __tablename__ = 'users'
    
#     id = db.Column(db.Integer, primary_key=True)
#     first_name = db.Column(db.String(100), nullable=False)
#     last_name = db.Column(db.String(100), nullable=False)
#     phoneno = db.Column(db.String(20), unique=True, nullable=False)
#     role = db.Column(db.String(20), nullable=False, default='WORKER') # 'ADMIN' or 'WORKER'

#     # --- Attendance & Payroll Mapping ---
#     # Matches the ID in the Excel Sheet
#     attendance_id = db.Column(db.String(50), unique=True, index=True, nullable=True)
#     monthly_salary = db.Column(db.Float, default=0.0)
#     daily_required_hours = db.Column(db.Float, default=8.0)

#     department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
#     is_active = db.Column(db.Boolean, default=True)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)

#     # Relationship to get a user's full history easily
#     attendance_records = db.relationship('Attendance', backref='employee', lazy=True, cascade="all, delete-orphan")

#     def to_dict(self, is_admin=False):
#         """
#         Returns a dictionary representation of the user.
#         Sensitive payroll data is only included if is_admin is True.
#         """
#         data = {
#             "id": self.id,
#             "first_name": self.first_name,
#             "last_name": self.last_name,
#             "full_name": f"{self.first_name} {self.last_name}",
#             "phone": self.phoneno,
#             "role": self.role,
#             "department_id": self.department_id,
#             "attendance_id": self.attendance_id,
#             "is_active": self.is_active
#         }

#         if is_admin:
#             data.update({
#                 "monthly_salary": self.monthly_salary,
#                 "daily_required_hours": self.daily_required_hours,
#                 "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S')
#             })
        
#         return data

from app.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    phoneno = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default='WORKER') # 'ADMIN' or 'WORKER'

    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # --- NEW: ROBUST PAYROLL MAPPING ---
    attendance_id = db.Column(db.String(50), unique=True, index=True, nullable=True)
    
    pay_type = db.Column(db.String(20), default='FIXED') # 'FIXED', 'DAILY', 'HOURLY'
    base_pay = db.Column(db.Float, default=0.0) # Represents Monthly Salary, Daily Rate, or Hourly Rate based on pay_type
    daily_required_hours = db.Column(db.Float, default=8.0)
    
    overtime_eligible = db.Column(db.Boolean, default=False)
    overtime_rate = db.Column(db.Float, default=0.0) # Flat rate per hour of OT

    # Relationship to get a user's full history easily
    attendance_records = db.relationship(
    'Attendance', 
    backref='employee', 
    lazy=True, 
    cascade="all, delete-orphan",
    foreign_keys="[Attendance.user_id]"  # 👈 Explicitly tell it which key to use
)

    def to_dict(self, is_admin=False):
        data = {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": f"{self.first_name} {self.last_name}",
            "phone": self.phoneno,
            "role": self.role,
            "department_id": self.department_id,
            "attendance_id": self.attendance_id,
            "is_active": self.is_active
        }

        if is_admin:
            data.update({
                "pay_type": self.pay_type,
                "base_pay": self.base_pay,
                "daily_required_hours": self.daily_required_hours,
                "overtime_eligible": self.overtime_eligible,
                "overtime_rate": self.overtime_rate,
                "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        
        return data