import os
import jwt
from flask import request, g, jsonify, current_app
from functools import wraps
from app.models.user import User


def jwt_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"message": "Authorization token missing"}), 401

        token = auth_header.split(" ")[1]

        try:
            payload = jwt.decode(
                token,
                current_app.config["SECRET_KEY"],
                algorithms=['HS256'],
            )
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token"}), 401

        user_id = payload.get("user_id")

        if not user_id:
            return jsonify({"message": "Invalid token payload"}), 401

        user = User.query.get(user_id)

        if not user:
            return jsonify({"message": "User not found"}), 401

        # Attach user info to request context
        g.current_user = user
        g.role = user.role
        g.department_id = user.department_id

        return fn(*args, **kwargs)

    return wrapper
