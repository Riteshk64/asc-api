# from app.extensions import db
# from datetime import datetime

# class User(db.Model):
#     __tablename__ = 'users'
    
#     id = db.Column(db.Integer, primary_key=True)
#     first_name = db.Column(db.String(100), nullable=True)
#     last_name = db.Column(db.String(100), nullable=True)
#     phoneno = db.Column(db.String(20), unique=True, nullable=False)
#     role = db.Column(db.String(20), nullable=False, default='USER') 

#     department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
#     approval_status = db.Column(db.String(20), default='APPROVED')  # 'APPROVED', 'PENDING_SIGNUP', 'PENDING_DEPT_CHANGE'
#     requested_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
#     is_active = db.Column(db.Boolean, default=True) # Keep is_active as is (for admin deactivation toggle)
#     created_at = db.Column(db.DateTime, default=datetime.utcnow)

#     # --- NEW: ROBUST PAYROLL MAPPING ---
#     attendance_id = db.Column(db.String(50), unique=True, index=True, nullable=True)
    
#     pay_type = db.Column(db.String(20), default='FIXED') # 'FIXED', 'DAILY', 'HOURLY'
#     base_pay = db.Column(db.Float, default=0.0) # Represents Monthly Salary, Daily Rate, or Hourly Rate based on pay_type
#     daily_required_hours = db.Column(db.Float, default=8.0)
    
#     overtime_eligible = db.Column(db.Boolean, default=False)
#     overtime_rate = db.Column(db.Float, default=0.0) # Flat rate per hour of OT

#     # Relationship to get a user's full history easily
#     attendance_records = db.relationship(
#         "Attendance",
#         back_populates="user",
#         lazy=True,
#         cascade="all, delete-orphan",
#         foreign_keys="Attendance.user_id"
#     )

#     def to_dict(self, is_admin=False):
#         data = {
#             "id": self.id,
#             "first_name": self.first_name,
#             "last_name": self.last_name,
#             "full_name": f"{self.first_name} {self.last_name}",
#             "phone": self.phoneno,
#             "role": self.role,
#             "department_id": self.department_id,
#             "attendance_id": self.attendance_id,
#             "is_active": self.is_active,
#             "approval_status": self.approval_status,
#             "requested_department_id": self.requested_department_id,
#         }

#         if is_admin:
#             data.update({
#                 "pay_type": self.pay_type,
#                 "base_pay": self.base_pay,
#                 "daily_required_hours": self.daily_required_hours,
#                 "overtime_eligible": self.overtime_eligible,
#                 "overtime_rate": self.overtime_rate,
#                 "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S')
#             })
        
#         return data


from app.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=True)
    last_name = db.Column(db.String(100), nullable=True)
    phoneno = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), nullable=False, default='USER') 

    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    approval_status = db.Column(db.String(20), default='APPROVED')  # 'APPROVED', 'PENDING_SIGNUP', 'PENDING_DEPT_CHANGE'
    requested_department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True) 
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    device_id = db.Column(db.String(255), nullable=True)

    # --- NEW: ROBUST PAYROLL MAPPING ---
    attendance_id = db.Column(db.String(50), unique=True, index=True, nullable=True)
    
    pay_type = db.Column(db.String(20), default='FIXED') # 'FIXED', 'DAILY', 'HOURLY'
    base_pay = db.Column(db.Float, default=0.0) 
    daily_required_hours = db.Column(db.Float, default=8.0)
    
    overtime_eligible = db.Column(db.Boolean, default=False)
    overtime_rate = db.Column(db.Float, default=0.0) 
    trusted_devices = db.Column(db.Text, default="") 
    trusted_device_names = db.Column(db.Text, default="") # 👈 NEW: "iPhone 14, Windows Chrome"
    
    pending_device_id = db.Column(db.String(255), nullable=True) 
    pending_device_name = db.Column(db.String(255), nullable=True)

    # Relationships
    attendance_records = db.relationship(
        "Attendance",
        back_populates="user",
        lazy=True,
        cascade="all, delete-orphan",
        foreign_keys="Attendance.user_id"
    )
    

    department = db.relationship('Department', backref='workers', foreign_keys=[department_id], lazy='joined')

    def to_dict(self, is_admin=False):
        
        derived_permissions = []
        if self.role == 'ADMIN':
            derived_permissions = ['ADMIN_ALL_ACCESS']
        elif self.department and self.department.permissions:
            # 👇 FIX: Since it's a JSON column, it's already a list of strings!
            # No need for the [p.name for p...] loop.
            derived_permissions = self.department.permissions 

        data = {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": f"{self.first_name} {self.last_name}",
            "phone": self.phoneno,
            "role": self.role,
            "department_id": self.department_id,
            "attendance_id": self.attendance_id,
            "is_active": self.is_active,
            "approval_status": self.approval_status,
            "requested_department_id": self.requested_department_id,
            "permissions": derived_permissions
        }

        if is_admin:
            data.update({
                "pay_type": self.pay_type,
                "base_pay": self.base_pay,
                "daily_required_hours": self.daily_required_hours,
                "overtime_eligible": self.overtime_eligible,
                "overtime_rate": self.overtime_rate,
                "created_at": self.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                "pending_device_name": self.pending_device_name, 
                "trusted_device_names": self.trusted_device_names
            })
            
        
        return data