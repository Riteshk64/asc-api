from flask import Blueprint, request, jsonify, current_app
from app.auth.firebase import verify_firebase_token
from app.auth.jwt_utils import generate_jwt
from app.models.user import User
from app.extensions import db
from app.models.department import Department
from app.auth.jwt_middleware import jwt_required
from flask import g
from app.models.contractor import Contractor
from app.models.supplier import Supplier

auth = Blueprint('auth', __name__, url_prefix='/auth')

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
    # Safely get the user from the global context
    user = getattr(g, 'current_user', None)

    # ✅ IF USER WAS DELETED IN SUPABASE, RETURN 401 TO TRIGGER FRONTEND LOGOUT
    if not user:
        return jsonify({"message": "User not found or deleted"}), 401

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

    # ✅ FIXED: Use 'user.first_name', NOT 'user.current_user.first_name'
    return jsonify({
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phoneno,
        "role": user.role,               
        "department_id": user.department_id, 
        "department_name": department_name,
        "allowed_menus": allowed_menus,
        "is_active": user.is_active,
        "approval_status": user.approval_status,
        "requested_department_id": user.requested_department_id
    }), 200



from app.models.contractor import Contractor
from app.models.supplier import Supplier

@auth.route("/verify-phone", methods=["POST"])
def verify_phone():
    data = request.get_json()
    firebase_token = data.get("firebase_token")
    device_id = data.get("device_id") 
    device_name = data.get("device_name", "Unknown Device")

    if not firebase_token or not device_id:
        return jsonify({"success": False, "message": "Tokens required."}), 400

    try:
        decoded = verify_firebase_token(firebase_token)
        phone = decoded.get("phone_number")
    except Exception as e:
        return jsonify({"success": False, "message": "Invalid Firebase Token"}), 401

    user = User.query.filter_by(phoneno=phone).first()

    if not user:
        existing_contractor = Contractor.query.filter_by(phone=phone).first()
        existing_supplier = Supplier.query.filter_by(phone_number=phone).first()

        if existing_contractor:
            user = User(
                first_name=existing_contractor.name, phoneno=phone, role='CLIENT',
                department_id=existing_contractor.department_id, is_active=False,
                approval_status='PENDING_SIGNUP', 
                trusted_devices=str(device_id).strip(), trusted_device_names=str(device_name).strip()
            )
        elif existing_supplier:
            user = User(
                first_name=existing_supplier.name, phoneno=phone, role='SUPPLIER',
                department_id=existing_supplier.department_id, is_active=False,
                approval_status='PENDING_SIGNUP', 
                trusted_devices=str(device_id).strip(), trusted_device_names=str(device_name).strip()
            )
        else:
            user = User(
                phoneno=phone, is_active=False, role='USER',  
                approval_status='PENDING_SIGNUP', 
                trusted_devices=str(device_id).strip(), trusted_device_names=str(device_name).strip()
            )
            
        db.session.add(user)
        db.session.commit()
    else:
        # --- EXISTING USER LOGIN ATTEMPT ---
        
        # 1. LEGACY DEVICE MIGRATOR (Safely removes None strings)
        old_device = str(user.device_id or "").strip()
        if old_device and old_device != "None" and not user.trusted_devices:
            user.trusted_devices = old_device
            user.trusted_device_names = "Original Device"
            db.session.commit()

        # 2. BULLETPROOF FIREWALL CHECK
        trusted_str = str(user.trusted_devices or "")
        # Splits by comma and perfectly trims every single ID to prevent space mismatches
        trusted_list = [d.strip() for d in trusted_str.split(',') if d.strip()]
        
        current_device = str(device_id or "").strip()

        if current_device and current_device not in trusted_list and user.role != 'ADMIN':
            # THE FIREWALL: Unrecognized Device!
            user.pending_device_id = current_device
            user.pending_device_name = str(device_name or "Unknown Device").strip()
            user.approval_status = 'PENDING_NEW_DEVICE'
            user.is_active = False 
            db.session.commit()
            
        elif user.approval_status == 'PENDING_NEW_DEVICE' and current_device in trusted_list:
            # 🛡️ THE AUTO-UNLOCK FAILSAFE: 
            # If they got locked out on a new laptop, but log in again on their original trusted phone, UNFREEZE them!
            user.approval_status = 'APPROVED'
            user.is_active = True
            user.pending_device_id = None
            user.pending_device_name = None
            db.session.commit()

    g.current_user = user
    g.user_id = user.id
    g.role = user.role
    g.department_id = user.department_id

    is_profile_done = bool(user.first_name and user.department_id)
    token = generate_jwt(
        {"user_id": user.id, "role": user.role, "department_id": user.department_id},
        expires_in_minutes=60 * 24 * 7 
    )

    return jsonify({
        "token": token, "profile_complete": is_profile_done,
        "is_active": user.is_active, "role": user.role
    }), 200


@auth.route("/create-profile", methods=["POST"])
@jwt_required 
def create_profile():
    data = request.get_json()
    
    user = getattr(g, 'current_user', None)
    if not user:
        return jsonify({"message": "User not found"}), 404

    user.first_name = data.get("first_name")
    user.last_name = data.get("last_name")
    user.department_id = data.get("department_id")
    
    # ✅ SET THEM TO PENDING, DO NOT ACTIVATE THEM!
    user.approval_status = 'PENDING_SIGNUP' 
    user.is_active = False
    
    db.session.commit()

    new_token = generate_jwt(
        {
            "user_id": user.id,
            "role": user.role,
            "department_id": user.department_id,
        },
        expires_in_minutes=60 * 24 * 7
    )

    return jsonify({
        "token": new_token,
        "profile_complete": True,  # Frontend sees: Profile done
        "is_active": False,        # Frontend sees: Not approved yet
        "role": user.role
    }), 200

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

    if user.role != 'ADMIN' and 'department_id' in data:
        new_dept_id = int(data['department_id'])
        if user.department_id != new_dept_id:
            dept = Department.query.get(new_dept_id)
            if not dept:
                return jsonify({"error": "Invalid Department ID"}), 400

            user.requested_department_id = new_dept_id
            user.approval_status = "PENDING_DEPT_CHANGE"

            user.is_active = False 
            
            db.session.commit()
            return jsonify({
                "message": "Department change requested. Account locked.",
                "approval_status": "PENDING_DEPT_CHANGE",
                "is_active": False
            }), 200

        

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
