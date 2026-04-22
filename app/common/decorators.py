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
def requires_permission(*required_permissions):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not hasattr(g, "current_user") or not g.current_user:
                return jsonify({"success": False, "message": "Unauthorized"}), 401

            if getattr(g, 'role', None) == 'ADMIN':
                return fn(*args, **kwargs)

            if not g.current_user.department:
                return jsonify({"success": False, "message": "Forbidden: No department"}), 403

            # 👇 FIX: Read directly from the JSON list (default to empty list if None)
            dept_permissions = g.current_user.department.permissions or []
            
            has_access = any(perm in dept_permissions for perm in required_permissions)

            if not has_access:
                needed = " or ".join(required_permissions)
                return jsonify({
                    "success": False, 
                    "message": f"Forbidden: Your department requires the '{needed}' permission"
                }), 403

            return fn(*args, **kwargs)
        return wrapper
    return decorator