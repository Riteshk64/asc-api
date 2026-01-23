from functools import wraps
from flask import g, jsonify

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

def admin_only(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.current_user.role != "ADMIN":
            return jsonify({"success": False, "message": "Forbidden"}), 403
        return f(*args, **kwargs)
    return wrapper

def department_required(department_id):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if g.current_user.department_id != department_id:
                return jsonify({"success": False, "message": "Forbidden"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator

def contractor_access_only(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if g.current_user.department_id not in [1, 2]:  # Brass, Moulding
            return jsonify({"success": False, "message": "Forbidden"}), 403
        return f(*args, **kwargs)
    return wrapper
