from functools import wraps
from flask import g, jsonify

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return jsonify({"success": False, "message": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper

def admin_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.role != "ADMIN":
            return jsonify({"message": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapper

def department_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        route_department_id = kwargs.get("department_id")

        if route_department_id is None:
            return jsonify({"message": "Department not specified"}), 400

        if g.department_id != route_department_id:
            return jsonify({"message": "Access denied for this department"}), 403

        return fn(*args, **kwargs)
    return wrapper

def contractor_access(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if g.department_id not in [1, 2]:  # Brass=1, Moulding=2
            return jsonify({"message": "Contractor access not allowed"}), 403
        return fn(*args, **kwargs)
    return wrapper
