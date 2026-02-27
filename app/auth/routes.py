import os  
from flask import Blueprint, request, jsonify, current_app
from app.auth.firebase import verify_firebase_token
from app.auth.jwt_utils import generate_jwt
from app.models.user import User
from app.extensions import db
from app.models.department import Department
import jwt
from app.common.decorators import admin_only
from app.auth.jwt_middleware import jwt_required
from flask import g


auth = Blueprint('auth', __name__, url_prefix='/auth')

@jwt_required
def get_department_name(dept_id, role):
    if dept_id: 
        dept = Department.query.get(dept_id)
        if dept: 
            return dept.name
    
    elif dept_id is None and role == "ADMIN":
        
        return "Administration"
    
    else: 
        return "Unknown"
    
@auth.route("/my-details", methods=["GET"])
@jwt_required
def get_current_user():
    # Safely get the user from the global context
    user = getattr(g, 'current_user', None)

    # ✅ IF USER WAS DELETED IN SUPABASE, RETURN 401 TO TRIGGER FRONTEND LOGOUT
    if not user:
        return jsonify({"message": "User not found or deleted"}), 401

    allowed_menus = [] 

    if user.role == "ADMIN":
        allowed_menus = [
            'admin_panel', 'transactions', 'recycle-bin', 
            'suppliers', 'contractors', 'products', 'settings', 'clients'
        ]
        department_name = "Administration"

    else:
        dept = Department.query.get(user.department_id)
        
        if dept and dept.permissions:
            allowed_menus = dept.permissions 
        else:
            allowed_menus = ['products', 'settings']
            
        department_name = dept.name if dept else "Unknown"

    # ✅ FIXED: Use 'user.first_name', NOT 'user.current_user.first_name'
    return jsonify({
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phoneno,
        "role": user.role,               
        "department_id": user.department_id, 
        "department_name": department_name,
        "allowed_menus": allowed_menus,
        "is_active": user.is_active,
        "approval_status": user.approval_status,
        "requested_department_id": user.requested_department_id
    }), 200
@auth.route("/verify-phone", methods=["POST"])
def verify_phone():
    data = request.get_json()
    firebase_token = data.get("firebase_token")

    if not firebase_token:
        return jsonify({"success": False, "message": "Token required"}), 400

    try:
        decoded = verify_firebase_token(firebase_token)
        phone = decoded.get("phone_number")
    except Exception as e:
        return jsonify({"success": False, "message": "Invalid Firebase Token"}), 401

    user = User.query.filter_by(phoneno=phone).first()

    # ✅ 1. CREATE ROW IMMEDIATELY IF IT DOESN'T EXIST
    if not user:
        user = User(
            phoneno=phone,
            is_active=False,
            role='USER',  
            approval_status='PENDING_SIGNUP' # Starts here
        )
        db.session.add(user)
        db.session.commit()

    # ✅ 2. PROFILE IS COMPLETE ONLY IF THEY HAVE A NAME
    is_profile_done = bool(user.first_name and user.department_id)

    # ✅ 3. ISSUE A REAL TOKEN WITH A USER ID
    token = generate_jwt(
        {
            "user_id": user.id,
            "role": user.role,
            "department_id": user.department_id,
        },
        expires_in_minutes=60 * 24 * 7 
    )

    return jsonify({
        "token": token,
        "profile_complete": is_profile_done,
        "is_active": user.is_active,
        "role": user.role
    }), 200

@auth.route("/create-profile", methods=["POST"])
@jwt_required 
def create_profile():
    data = request.get_json()
    
    user = getattr(g, 'current_user', None)
    if not user:
        return jsonify({"message": "User not found"}), 404

    user.first_name = data.get("first_name")
    user.last_name = data.get("last_name")
    user.department_id = data.get("department_id")
    
    # ✅ SET THEM TO PENDING, DO NOT ACTIVATE THEM!
    user.approval_status = 'PENDING_SIGNUP' 
    user.is_active = False
    
    db.session.commit()

    new_token = generate_jwt(
        {
            "user_id": user.id,
            "role": user.role,
            "department_id": user.department_id,
        },
        expires_in_minutes=60 * 24 * 7
    )

    return jsonify({
        "token": new_token,
        "profile_complete": True,  # Frontend sees: Profile done
        "is_active": False,        # Frontend sees: Not approved yet
        "role": user.role
    }), 200


@auth.route("/profile/update", methods=["PUT"])
@jwt_required
def update_profile():
    user = g.current_user
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()

    # 1. Update Basic Info
    if 'first_name' in data:
        user.first_name = data['first_name']
    if 'last_name' in data:
        user.last_name = data['last_name']

    if user.role != 'ADMIN' and 'department_id' in data:
        new_dept_id = int(data['department_id'])
        if user.department_id != new_dept_id:
            dept = Department.query.get(new_dept_id)
            if not dept:
                return jsonify({"error": "Invalid Department ID"}), 400

            user.requested_department_id = new_dept_id
            user.approval_status = "PENDING_DEPT_CHANGE"

            user.is_active = False 
            
            db.session.commit()
            return jsonify({
                "message": "Department change requested. Account locked.",
                "approval_status": "PENDING_DEPT_CHANGE",
                "is_active": False
            }), 200

        

    # 3. Save standard changes (if account wasn't locked above)
    try:
        db.session.commit()
        return jsonify({
            "message": "Profile updated successfully",
            "is_active": user.is_active,
            "first_name": user.first_name,
            "last_name": user.last_name
        }), 200
 
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@auth.route("/test")
def test():
    return jsonify({"message": "Auth route is working!"})
