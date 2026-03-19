# import os
# import jwt
# from flask import request, g, jsonify, current_app
# from functools import wraps
# from app.models.user import User


# def jwt_required(fn):
#     @wraps(fn)
#     def wrapper(*args, **kwargs):
#         auth_header = request.headers.get("Authorization")

#         if not auth_header or not auth_header.startswith("Bearer "):
#             return jsonify({"message": "Authorization token missing"}), 401

#         token = auth_header.split(" ")[1]

#         try:
#             payload = jwt.decode(
#                 token,
#                 current_app.config["SECRET_KEY"],
#                 algorithms=['HS256'],
#             )
#         except jwt.ExpiredSignatureError:
#             return jsonify({"message": "Token expired"}), 401
#         except jwt.InvalidTokenError:
#             return jsonify({"message": "Invalid token"}), 401

#         user_id = payload.get("user_id")

#         if not user_id:
#             return jsonify({"message": "Invalid token payload"}), 401

#         user = User.query.get(user_id)

#         if not user:
#             return jsonify({"message": "User not found"}), 401
        
#         if not user.is_active:
#             return jsonify({"message": "Account is inactive. Please contact Admin."}), 403

#         # Attach user info to request context
#         g.current_user = user
#         g.role = user.role
#         g.department_id = user.department_id

#         return fn(*args, **kwargs)
    
#     return wrapper


import jwt
from functools import wraps
from flask import request, jsonify, g, current_app
from app.models.user import User 

def jwt_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"message": "Authorization token missing"}), 401
            
        token = auth_header.split(" ")[1]
        
        try:
            # 1. Decode the token
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])

            user_id = payload.get('user_id')
            
            # ... fetch the database user
            user = User.query.get(user_id)

            if not user:
                return jsonify({"message": "User not found or deleted"}), 401

            g.current_user = user
            
            # ✅ FIX: Use the DATABASE values, not the TOKEN values
            # This ensures that if an admin changes a user's dept, 
            # the user doesn't have to log out/in to see the change.
            g.user_id = user.id
            g.role = user.role
            g.department_id = user.department_id

            current_app.logger.info("request_started")
            
            # ✅ CRITICAL FIX: If user was deleted in Supabase, return 401 immediately!
            # This triggers the frontend to log them out and go to Sign In.
            if not user:
                return jsonify({"message": "User not found or deleted"}), 401

            # 5. Attach the full user to the global context
            g.current_user = user

            # 6. Check User Status in the Database
            if not user.is_active:
                current_status = str(getattr(user, 'approval_status', ''))
                
                # Allow these specific statuses through the gate
                valid_statuses = ['PENDING_SIGNUP', 'PENDING_DEPT_CHANGE']
                
                if current_status not in valid_statuses:
                    return jsonify({"message": "Account inactive or pending Admin approval"}), 403

        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token payload"}), 401
        except Exception as e:
            # Catch DB/Parsing errors so it doesn't crash the server silently
            return jsonify({"message": f"Middleware Error: {str(e)}"}), 500

        return fn(*args, **kwargs)
    return wrapper