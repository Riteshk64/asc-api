from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from app.extensions import db
from app.models import User, Attendance


attendance = Blueprint('attendance', __name__, url_prefix='/attendance')

@attendance.route('/log', methods=['POST'])
@jwt_required()
def log_attendance():
    admin_id = get_jwt_identity()
    admin = User.query.get(admin_id)

    # 1. SECURITY: Only Admins can log attendance
    if not admin or admin.role.upper() != 'ADMIN':
        return jsonify({"error": "Unauthorized. Admins only."}), 403

    data = request.json
    user_id = data.get('user_id')
    date_str = data.get('date') # Expected format: 'YYYY-MM-DD'
    status = data.get('status', 'PRESENT').upper()
    hours_worked = float(data.get('hours_worked', 0.0))
    overtime_hours = float(data.get('overtime_hours', 0.0))

    worker = User.query.get(user_id)
    if not worker:
        return jsonify({"error": "Worker not found"}), 404

    try:
        log_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD"}), 400

    # 2. THE MATH ENGINE
    daily_base_earnings = 0.0
    daily_overtime_earnings = 0.0

    # Calculate Overtime (if eligible)
    if worker.overtime_eligible and overtime_hours > 0:
        daily_overtime_earnings = overtime_hours * worker.overtime_rate

    # Calculate Base Earnings based on Pay Type
    if status == 'PRESENT':
        if worker.pay_type == 'HOURLY':
            daily_base_earnings = hours_worked * worker.base_pay
        elif worker.pay_type == 'DAILY':
            daily_base_earnings = worker.base_pay
        # If 'FIXED', daily_base_earnings remains 0.0 (monthly salary handles their base pay)

    elif status == 'HALF_DAY':
        if worker.pay_type == 'HOURLY':
            daily_base_earnings = hours_worked * worker.base_pay
        elif worker.pay_type == 'DAILY':
            daily_base_earnings = worker.base_pay / 2.0
        # For 'FIXED', you might handle half-day deductions at the end of the month

    total_daily_earnings = daily_base_earnings + daily_overtime_earnings

    # 3. UPSERT LOGIC (Update if exists, else Create)
    existing_log = Attendance.query.filter_by(user_id=worker.id, date=log_date).first()

    if existing_log:
        existing_log.status = status
        existing_log.hours_worked = hours_worked
        existing_log.overtime_hours = overtime_hours
        existing_log.logged_pay_type = worker.pay_type
        existing_log.hourly_rate_at_time = worker.base_pay
        existing_log.overtime_rate_at_time = worker.overtime_rate
        existing_log.daily_base_earnings = daily_base_earnings
        existing_log.daily_overtime_earnings = daily_overtime_earnings
        existing_log.total_daily_earnings = total_daily_earnings
        existing_log.created_by = admin.id
        existing_log.department_id = worker.department_id
    else:
        new_log = Attendance(
            user_id=worker.id,
            department_id=worker.department_id,
            date=log_date,
            status=status,
            hours_worked=hours_worked,
            overtime_hours=overtime_hours,
            logged_pay_type=worker.pay_type,
            hourly_rate_at_time=worker.base_pay,
            overtime_rate_at_time=worker.overtime_rate,
            daily_base_earnings=daily_base_earnings,
            daily_overtime_earnings=daily_overtime_earnings,
            total_daily_earnings=total_daily_earnings,
            created_by=admin.id
        )
        db.session.add(new_log)

    db.session.commit()

    return jsonify({
        "message": "Attendance logged successfully",
        "total_earnings_today": total_daily_earnings
    }), 200