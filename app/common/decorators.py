from functools import wraps
from flask import g, jsonify

# Department constants
BRASS = 1
MOULDING = 2
POWDER = 3
FINISHED_GOODS = 4

def admin_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        if g.role != "ADMIN":
            return jsonify({"success": False, "message": "Admin access required"}), 403

        return fn(*args, **kwargs)
    return wrapper


# def department_only(fn):
#     @wraps(fn)
#     def wrapper(*args, **kwargs):
#         if not getattr(g, "current_user", None):
#             return jsonify({"success": False, "message": "Unauthorized"}), 401

#         route_department_id = kwargs.get("department_id")

#         if route_department_id is None:
#             return jsonify({"success": False, "message": "Department not specified"}), 400

#         if g.department_id != route_department_id:
#             return jsonify({"success": False, "message": "Access denied for this department"}), 403

#         return fn(*args, **kwargs)
#     return wrapper


def contractor_access(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return jsonify({"success": False, "message": "Unauthorized"}), 401

        if g.role == "ADMIN":
            return fn(*args, **kwargs)
        
        if g.department_id not in (BRASS, MOULDING):
            return jsonify(
                {"success": False, "message": "Contractor access not allowed"},
                403
            )

        return fn(*args, **kwargs)
    return wrapper
