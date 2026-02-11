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

# app/auth/routes.py

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
    user = g

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

    return jsonify({
        "first_name": user.current_user.first_name,
        "last_name": user.current_user.last_name,
        "phone": user.current_user.phoneno,
        "role": user.role,               
        "department_id": user.department_id, 
        "department_name": department_name,
        "allowed_menus": allowed_menus
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

    # Check if user exists
    user = User.query.filter_by(phoneno=phone).first()

    if user:
        token = generate_jwt(
            {
                "user_id": user.id,
                "role": user.role,
                "department_id": user.department_id,
                "profile_complete": True
            },
            expires_in_minutes=60 * 24 * 7
        )

        return jsonify({
            "token": token,
            "profile_complete": True
        }), 200

    temp_token = generate_jwt(
        {
            "phone": phone,
            "profile_complete": False
        },
        expires_in_minutes=15
    )

    return jsonify({
        "token": temp_token,
        "profile_complete": False
    }), 200

@auth.route("/create-profile", methods=["POST"])
def create_profile():
    # 1. Verify Token
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return jsonify({"message": "Missing token"}), 401
        
    try:
        token = auth_header.split(" ")[1]
        decoded = jwt.decode(
            token,
            current_app.config["SECRET_KEY"],
            algorithms=['HS256'],
        )
        phone = decoded.get("phone")
    except Exception:
        return jsonify({"message": "Invalid or expired token"}), 401

    # 2. Get Input
    data = request.get_json()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    dept_input = data.get("department_id")

    
    admin_phone_env = os.environ.get("ADMIN_PHONE", "")

    if admin_phone_env and phone == admin_phone_env:
        
        final_role = "ADMIN"
        final_dept_id = None 
        print(f"👑 Admin identified: {phone}")

    else:
       
        final_role = "USER"
        final_dept_id = dept_input
        
    
        if not final_dept_id:
            return jsonify({"message": "Regular users must select a department"}), 400


        dept = Department.query.get(final_dept_id)
        if not dept:
            return jsonify({"message": "Invalid Department ID Selected"}), 400

    

    user = User(
        first_name=first_name,
        last_name=last_name,
        phoneno=phone,
        role=final_role,
        department_id=final_dept_id,
    )

    try:
        db.session.add(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": "Error creating profile", "error": str(e)}), 500

    token = generate_jwt(
        {
            "user_id": user.id,
            "role": user.role,
            "department_id": user.department_id,
            "profile_complete": True
        },
        expires_in_minutes=60 * 24 * 7
    )

    return jsonify({"token": token, "role": final_role})


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

    # 2. Handle Department Change (Only for Non-Admins)
    # If a regular worker changes their department, we lock the account (is_active=False)
    # so an Admin must approve the transfer.
    if user.role != 'ADMIN' and 'department_id' in data:
        try:
            new_dept_id = int(data['department_id'])
            
            # Only act if the department is ACTUALLY changing
            if user.department_id != new_dept_id:
                # Verify the new department exists
                dept = Department.query.get(new_dept_id)
                if not dept:
                    return jsonify({"error": "Invalid Department ID"}), 400

                user.department_id = new_dept_id
                user.is_active = False  # LOCK ACCOUNT
                
                db.session.commit()
                return jsonify({
                    "message": "Department changed. Account locked pending approval.",
                    "is_active": False
                }), 200

        except (ValueError, TypeError):
            return jsonify({"error": "Invalid Department Format"}), 400

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


