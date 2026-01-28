from flask import Blueprint, request, jsonify
from app.auth.firebase import verify_firebase_token
from app.auth.jwt_utils import generate_jwt
from app.models.user import User
from app.extensions import db
import jwt
from flask import current_app

auth = Blueprint('auth',__name__,url_prefix='/auth')

@auth.route("/verify-phone", methods=["POST"])
def verify_phone():
    data = request.get_json()
    firebase_token = data.get("firebase_token")

    if not firebase_token:
        return jsonify({"success": False, "message": "Token required"}), 400

    decoded = verify_firebase_token(firebase_token)
    phone = decoded.get("phone_number")

    user = User.query.filter_by(phoneno=phone).first()  # phone as identity

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
        return jsonify({"token": token})

    # New user → temporary JWT
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
    auth_header = request.headers.get("Authorization")
    token = auth_header.split(" ")[1]

    decoded = jwt.decode(
        token,
        current_app.config["SECRET_KEY"],
        algorithms=["HS256"]
    )

    phone = decoded.get("phone")

    data = request.get_json()
    first_name = data.get("first_name")
    last_name = data.get("last_name")
    department_id = data.get("department_id")

    user = User(
        first_name=first_name,
        last_name=last_name,
        phoneno=phone,
        role="USER",
        department_id=department_id,
    )

    db.session.add(user)
    db.session.commit()

    token = generate_jwt(
        {
            "user_id": user.id,
            "role": user.role,
            "department_id": user.department_id,
            "profile_complete": True
        },
        expires_in_minutes=60 * 24 * 7
    )

    return jsonify({"token": token})

@auth.route("/test", methods=["POST"])
def test():
    return jsonify({"message": "Auth route is working!"})