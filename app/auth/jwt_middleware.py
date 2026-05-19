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
            payload = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=["HS256"])
            user_id = payload.get('user_id')
            
            # 1. Check if user exists
            user = User.query.get(user_id)
            if not user:
                return jsonify({"message": "User not found or deleted"}), 401

            # 2. Attach user to global Flask context
            g.current_user = user
            g.user_id = user.id
            g.role = user.role
            g.department_id = user.department_id

            current_app.logger.info("request_started")
        
            # 3. THE FIREWALL 
            # If the user is locked out (is_active = False), block them from everything
            # EXCEPT the endpoints needed to load the app and show the Pending Page.
            if not user.is_active:
                allowed_paths = ['/auth/my-details', '/auth/departments']
                
                # If they are trying to access /core/products, /core/orders, etc., block them!
                if not any(request.path.endswith(path) for path in allowed_paths):
                    return jsonify({"message": "Account inactive or pending Admin approval"}), 403

        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token payload"}), 401
        except Exception as e:
            return jsonify({"message": f"Middleware Error: {str(e)}"}), 500

        return fn(*args, **kwargs)
    return wrapper