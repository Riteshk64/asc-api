import os  
from flask import Blueprint, request, jsonify, current_app
from app.auth.firebase import verify_firebase_token
from app.auth.jwt_utils import generate_jwt
from app.models.user import User
from app.extensions import db
import jwt

auth = Blueprint('auth', __name__, url_prefix='/auth')

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
        return jsonify({"token": token, "profile_complete": True})

    # New user: Temporary token
    temp_token = generate_jwt({
        "phone": phone,
        "profile_complete": False
    }, expires_in_minutes=15)

    return jsonify({
        "token": temp_token,
        "profile_complete": False
    })

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

    # ============================================================
    # 🔒 SECURE ADMIN CHECK (Via Environment Variable)
    # ============================================================
    
    # We fetch from environment. Default to empty string to prevent crashing.
    admin_phone_env = os.environ.get("ADMIN_PHONE", "")

    # Compare strictly
    if admin_phone_env and phone == admin_phone_env:
        final_role = "ADMIN"
        final_dept_id = None 
        print(f"👑 Admin identified via ENV: {phone}")
    else:
        final_role = "USER"
        final_dept_id = dept_input
        print(f"User identified: {phone}. assigning USER role.")

    # ============================================================

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

@auth.route("/test")
def test():
    return jsonify({"message": "Auth route is working!"})