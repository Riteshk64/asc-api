from flask import Blueprint, jsonify, request, g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.extensions import db
from sqlalchemy import func, case, desc
from datetime import datetime, date
import calendar
from sqlalchemy.orm import joinedload
from sqlalchemy import or_

# Import ALL models
from app.models.department import Department
from app.models.supplier import Supplier
from app.models.contractor import Contractor
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.user import User  
from app.models.activity_log import ActivityLog
from app.models.attendance import Attendance

core = Blueprint('core', __name__, url_prefix='/core')


def get_active_department():
    
    if g.role == "ADMIN":
        try:
            dept_id = request.headers.get("X-Department-Id")
            return int(dept_id) if dept_id else None
        except ValueError:
            return None
    return g.department_id
# @core.route('/stock/operate', methods=['POST'])
# @jwt_required
# def stock_operation():
#     data = request.get_json()
#     sku = data.get('sku')
#     op_type = data.get('type')  # 'in', 'out', 'return', 'return_defective'
    
#     try:
#         qty = float(data.get('qty', 0))
#         if qty <= 0: raise ValueError
#     except ValueError:
#         return jsonify({"error": "Invalid positive quantity required"}), 400

#     if not sku or not op_type:
#         return jsonify({"error": "SKU and operation type are required"}), 400

#     active_dept = get_active_department()
#     if not active_dept:
#         return jsonify({"error": "Department context missing"}), 400

#     product = Product.query.filter_by(product_code=sku, department_id=active_dept).first()

#     if not product:
#         if op_type != 'in':
#             return jsonify({"error": "Product not found"}), 404

#         product_name = data.get('productName')
#         if not product_name:
#             return jsonify({"error": "Product Name is required for new products"}), 400

#         product = Product(
#             name=product_name, product_code=sku, unit=data.get('unit', 'pcs'),
#             category=data.get('category', 'General'), current_stock=0.0,
#             department_id=active_dept, is_active=True
#         )
#         db.session.add(product)
#         db.session.flush()

#     if product.department_id != active_dept:
#         return jsonify({"error": "You cannot operate on another department's stock"}), 403

#     supplier_id = None
#     contractor_id = None
#     default_name = "Manual Adjustment"

#     # --- STOCK IN (Supplier -> Inventory) ---
#     if op_type == 'in':
#         product.current_stock += qty
#         sup_name = (data.get('supplier_name') or default_name).strip()
#         supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
#         if not supplier:
#             supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
#             db.session.add(supplier)
#             db.session.flush()
#         supplier_id = supplier.id

#     # --- RETURN DEFECTIVE (Inventory -> Supplier) ---
#     elif op_type == 'return_defective':
#         if product.current_stock < qty:
#             return jsonify({"error": f"Insufficient stock to return. Current: {product.current_stock}"}), 400
        
#         product.current_stock -= qty
#         sup_name = (data.get('supplier_name') or default_name).strip()
#         supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
#         if not supplier:
#             supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
#             db.session.add(supplier)
#             db.session.flush()
#         supplier_id = supplier.id

#     # --- STOCK OUT (Inventory -> Contractor) ---
#     elif op_type == 'out':
#         if product.current_stock < qty:
#             return jsonify({"error": f"Insufficient stock. Current: {product.current_stock}"}), 400
#         product.current_stock -= qty
#         cont_name = (data.get('contractor_name') or default_name).strip()
#         contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
#         if not contractor:
#             contractor = Contractor(name=cont_name, is_active=True)
#             db.session.add(contractor)
#             db.session.flush()
#         contractor_id = contractor.id

#     # --- RETURN FROM CONTRACTOR (Contractor -> Inventory) ---
#     elif op_type == 'return':
        
#         # Scenario A: Returning defective stock TO a Supplier
#         if data.get('supplier_name'):
#             if product.current_stock < qty:
#                 return jsonify({"error": f"Insufficient stock to return. Current: {product.current_stock}"}), 400
            
#             product.current_stock -= qty  # Stock goes DOWN
#             sup_name = data.get('supplier_name').strip()
            
#             supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
#             if not supplier:
#                 supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
#                 db.session.add(supplier)
#                 db.session.flush()
#             supplier_id = supplier.id

#         # Scenario B: Receiving unused stock FROM a Contractor
#         else:
#             product.current_stock += qty  # Stock goes UP
#             cont_name = (data.get('contractor_name') or default_name).strip()
            
#             contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
#             if not contractor:
#                 contractor = Contractor(name=cont_name, is_active=True)
#                 db.session.add(contractor)
#                 db.session.flush()
#             contractor_id = contractor.id

#     txn = Transaction(
#         product_id=product.id, type=op_type, quantity=qty,
#         supplier_id=supplier_id, contractor_id=contractor_id,
#         department_id=active_dept, created_by=g.current_user.id, is_active=True 
#     )

#     try:
#         db.session.add(txn)
#         log = ActivityLog(
#             user_id=g.current_user.id,
#             action=f"Stock {op_type.upper()}: {qty} {product.unit} - {product.name}",
#             transaction_id=txn.id
#         )
#         db.session.add(log)
#         db.session.add(product) 
#         db.session.commit()
#         return jsonify({"message": "Stock updated successfully", "new_qty": product.current_stock}), 200
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"error": str(e)}), 500
    

@core.route('/stock/operate', methods=['POST'])
@jwt_required
def stock_operation():
    data = request.get_json()
    product_id = data.get('product_id') # 👈 NEW: Get specific ID
    sku = data.get('sku')
    product_name = data.get('productName')
    op_type = data.get('type')
    
    try:
        qty = float(data.get('qty', 0))
        if qty <= 0: raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid positive quantity required"}), 400

    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    # ==========================================
    # 1. SMART PRODUCT LOOKUP
    # ==========================================
    product = None

    # A. If we have an ID, use it (Most Reliable)
    if product_id:
        product = Product.query.get(product_id)
    
    # B. Fallback: Lookup by Name AND SKU (Since SKU alone isn't unique)
    if not product and sku and product_name:
        product = Product.query.filter_by(
            product_code=sku, 
            name=product_name, 
            department_id=active_dept
        ).first()

    # C. Final Fallback: SKU only (Only if we still haven't found it)
    if not product and sku:
        product = Product.query.filter_by(
            product_code=sku, 
            department_id=active_dept
        ).first()

    # ==========================================
    # 2. CREATE NEW PRODUCT (Only on 'in')
    # ==========================================
    if not product:
        if op_type != 'in':
            return jsonify({"error": "Product not found"}), 404

        if not product_name:
            return jsonify({"error": "Product Name required for new products"}), 400

        product = Product(
            name=product_name,
            product_code=sku,
            unit=data.get('unit', 'pcs'),
            category=data.get('category', 'General'),
            current_stock=0.0,
            department_id=active_dept,
            is_active=True
        )
        db.session.add(product)
        db.session.flush()

    # Security check
    if product.department_id != active_dept:
        return jsonify({"error": "Cross-department operation blocked"}), 403

    # ==========================================
    # 3. STOCK LOGIC (UNCHANGED)
    # ==========================================
    supplier_id = data.get('supplier_id')
    contractor_id = data.get('contractor_id')
    default_name = "Manual Adjustment"

    if op_type == 'in':
        product.current_stock += qty
        sup_name = (data.get('supplier_name') or default_name).strip()
        supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
        if not supplier:
            supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
            db.session.add(supplier)
            db.session.flush()
        supplier_id = supplier.id
        
    elif op_type == 'out':
        if product.current_stock < qty:
            return jsonify({"error": f"Insufficient stock ({product.current_stock})"}), 400
        product.current_stock -= qty
        cont_name = (data.get('contractor_name') or default_name).strip()
        contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
        if not contractor:
            contractor = Contractor(name=cont_name, is_active=True)
            db.session.add(contractor)
            db.session.flush()
        contractor_id = contractor.id

    elif op_type == 'return':
        
        # Scenario A: Returning defective stock TO a Supplier
        if data.get('supplier_name'):
            if product.current_stock < qty:
                return jsonify({"error": f"Insufficient stock to return. Current: {product.current_stock}"}), 400
            
            product.current_stock -= qty  # Stock goes DOWN
            sup_name = data.get('supplier_name').strip()
            
            supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
            if not supplier:
                supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
                db.session.add(supplier)
                db.session.flush()
            supplier_id = supplier.id

        # Scenario B: Receiving unused stock FROM a Contractor
        else:
            product.current_stock += qty  # Stock goes UP
            cont_name = (data.get('contractor_name') or default_name).strip()
            
            contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
            if not contractor:
                contractor = Contractor(name=cont_name, is_active=True)
                db.session.add(contractor)
                db.session.flush()
            contractor_id = contractor.id

    # Create Transaction using the correct product.id
    txn = Transaction(
        product_id=product.id, 
        type=op_type, 
        quantity=qty,
        supplier_id=supplier_id or data.get('supplier_id'),
        contractor_id=contractor_id or data.get('contractor_id'),
        department_id=active_dept,
        created_by=g.current_user.id,
        is_active=True 
    )

    try:
        db.session.add(txn)
        db.session.add(product) 
        db.session.commit()
        return jsonify({"message": "Stock updated", "new_qty": product.current_stock}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    
@core.route('/users/<int:id>', methods=['GET'])
@jwt_required
@admin_only
def get_user_details(id): 
    # Use .get() to find by primary key 'id'
    user = User.query.get(id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Security: Ensure Admin has access to this user's department
    active_dept = get_active_department()
    if active_dept and user.department_id != active_dept:
        return jsonify({"error": "Unauthorized: This user belongs to another department"}), 403

    # is_admin=True ensures pay_type, base_pay, etc. are included in the dict
    return jsonify(user.to_dict(is_admin=True)), 200
@core.route('/users/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_user_payroll_settings(id):
    user = User.query.get_or_404(id)
    data = request.json
    
    # 1. Update Pay Type
    if 'pay_type' in data:
        user.pay_type = data['pay_type'].upper()

    # 2. Safety Logic for Float Conversions
    # We use 'or 0.0' to handle cases where the DB or the Input is None
    user.base_pay = float(data.get('base_pay') or user.base_pay or 0.0)
    user.daily_required_hours = float(data.get('daily_required_hours') or user.daily_required_hours or 8.0)
    user.overtime_rate = float(data.get('overtime_rate') or user.overtime_rate or 0.0)
    
    # 3. Update Boolean
    if 'overtime_eligible' in data:
        user.overtime_eligible = bool(data['overtime_eligible'])
        
    db.session.commit()
    return jsonify({"message": "Settings updated"}), 200

@core.route('/attendance/log', methods=['POST'])
@jwt_required
@admin_only
def calculate_monthly_payout():
    data = request.json
    worker = User.query.get_or_404(data.get('user_id'))
    
    # --- Month Selection & Duplicate Check Logic ---
    month_year_str = data.get('month_year') 
    if month_year_str:
        try:
            target_year, target_month = map(int, month_year_str.split('-'))
        except ValueError:
            return jsonify({"error": "Invalid month format. Use YYYY-MM"}), 400
    else:
        today = datetime.utcnow().date()
        target_year, target_month = today.year, today.month
        
    first_day_of_month = date(target_year, target_month, 1)
    last_day_num = calendar.monthrange(target_year, target_month)[1]
    pay_period_date = date(target_year, target_month, last_day_num)

    existing_entry = Attendance.query.filter(
        Attendance.user_id == worker.id,
        Attendance.status == 'MONTHLY_SUMMARY',
        Attendance.date >= first_day_of_month,
        Attendance.date <= pay_period_date
    ).first()

    if existing_entry:
        return jsonify({
            "error": f"A payroll entry for {target_year}-{target_month:02d} already exists. Please delete it first if you need to amend it."
        }), 400

    # --- Calculations ---
    base_pay = float(worker.base_pay or 0.0)
    shift_hrs = float(worker.daily_required_hours or 8.0)
    
    # Inputs
    standard_days = float(data.get('standard_days', 27))
    actual_days = float(data.get('actual_days', 0))
    
    standard_hours = float(data.get('standard_hours', 216))
    actual_hours = float(data.get('actual_hours', 0))
    
    ot_hrs = float(data.get('overtime_hours', 0))
    
    final_payout = 0.0
    total_hours_logged = 0.0
    hourly_rate_at_time = 0.0

    if worker.pay_type == 'FIXED':
        final_payout = base_pay
        total_hours_logged = standard_days * shift_hrs 
        hourly_rate_at_time = (base_pay / standard_days) / shift_hrs if standard_days > 0 and shift_hrs > 0 else 0
    
    elif worker.pay_type == 'HOURLY':
        # Rate = Base / Standard Expected Hours
        hourly_rate = base_pay / standard_hours if standard_hours > 0 else 0
        total_hours_logged = actual_hours + ot_hrs
        
        # Payout = Total actual hours * rate
        final_payout = total_hours_logged * hourly_rate
        hourly_rate_at_time = hourly_rate

    elif worker.pay_type == 'DAILY':
        # Rate = Base / Standard Expected Days
        daily_rate = base_pay / standard_days if standard_days > 0 else 0
        hourly_conv = daily_rate / shift_hrs if shift_hrs > 0 else 0
        total_hours_logged = (actual_days * shift_hrs) + ot_hrs
        
        # Payout = (Actual days * daily rate) + OT
        final_payout = (actual_days * daily_rate) + (ot_hrs * hourly_conv)
        hourly_rate_at_time = hourly_conv

    # --- Save ---
    try:
        new_summary = Attendance(
            user_id=worker.id,
            date=pay_period_date, 
            status='MONTHLY_SUMMARY',
            hours_worked=total_hours_logged,
            overtime_hours=ot_hrs,
            logged_pay_type=worker.pay_type,
            total_daily_earnings=round(final_payout, 2),
            hourly_rate_at_time=round(hourly_rate_at_time, 4),
            created_by=g.current_user.id if hasattr(g, 'current_user') else None
        )
        db.session.add(new_summary)
        db.session.commit()
        
        return jsonify({"message": "Payout recorded", "earned": round(final_payout, 2)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/attendance/<int:log_id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_attendance_log(log_id):
    log = Attendance.query.get_or_404(log_id)
    
    try:
        db.session.delete(log)
        db.session.commit()
        return jsonify({"message": "Payroll record deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@core.route('/users/<int:id>/attendance', methods=['GET'])
@jwt_required
@admin_only
def get_user_attendance_history(id):
    worker = User.query.get(id)
    if not worker:
        return jsonify({"error": "Worker not found"}), 404

    # OPTIMIZED: Add pagination to avoid loading all records at once
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    per_page = min(per_page, 100)  # Cap at 100 to prevent abuse

    # Fetch logs with pagination, ordered by date (newest first)
    query = Attendance.query.filter_by(user_id=id).order_by(desc(Attendance.date))
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        "data": [log.to_dict() for log in paginated.items],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": paginated.total,
            "pages": paginated.pages
        }
    }), 200

# ==========================================
# 2. LISTS (Products & Transactions)
# ==========================================
@core.route('/products', methods=['GET'])
@jwt_required
def get_products():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    products = Product.query.filter_by(
        is_active=True,
        department_id=active_dept
    ).all()

    return jsonify([p.to_dict() for p in products]), 200



# @core.route('/products/<int:id>', methods=['PUT'])
# @jwt_required
# def update_product(id):
#     product = Product.query.get(id)
#     if not product: return jsonify({"error": "Product not found"}), 404

#     active_dept = get_active_department()
    
#     # Security: Only Admin or Dept Owner can edit
#     if product.department_id != active_dept and g.role != 'ADMIN':
#         return jsonify({"error": "Unauthorized"}), 403

#     data = request.get_json()
    

#     if 'name' in data: product.name = data['name']
#     if 'sku' in data: product.product_code = data['sku']
    

#     if 'min_stock' in data: 
#         try: product.min_stock = float(data['min_stock'])
#         except: pass
    
#     if 'max_stock' in data:
#         try: product.max_stock = float(data['max_stock'])
#         except: pass

#     try:
#         db.session.commit()
#         return jsonify({"message": "Product updated"}), 200
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"error": str(e)}), 500

@core.route('/products/<int:id>', methods=['PUT'])
@jwt_required
def update_product(id):
    try:
        # 1. Find Product
        product = Product.query.get(id)
        if not product: 
            return jsonify({"error": "Product not found"}), 404

        active_dept = get_active_department()
        
        # 2. Security Check (Allow Admin OR Department Owner)
        # Note: We check if role is NOT Admin AND Dept doesn't match
        if g.role != 'ADMIN' and product.department_id != active_dept:
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        
        # 3. Update Name
        if 'name' in data and data['name']:
            product.name = data['name']

        # 4. Update SKU (With Duplicate Check)
        if 'sku' in data and data['sku']:
            new_sku = data['sku'].strip()
            # Only check if the SKU is actually changing
            if new_sku != product.product_code:
                # Check if this SKU exists elsewhere
                product.product_code = new_sku
        
        # 5. Update Min Stock (Safe Conversion)
        if 'min_stock' in data: 
            try: 
                val = data['min_stock']
                # Handle empty strings or nulls by defaulting to 0
                if val == "" or val is None:
                    product.min_stock = 0.0
                else:
                    product.min_stock = float(val)
            except ValueError: 
                pass # Ignore invalid numbers (keep old value)
        
        # 6. Update Max Stock (Safe Conversion)
        if 'max_stock' in data:
            try: 
                val = data['max_stock']
                if val == "" or val is None:
                    product.max_stock = 0.0
                else:
                    product.max_stock = float(val)
            except ValueError: 
                pass 

        db.session.commit()
        return jsonify({"message": "Product updated"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Update Product Error: {str(e)}") 
        return jsonify({"error": f"Server Error: {str(e)}"}), 500
    
@core.route('/pending-users', methods=['GET'])
@jwt_required
@admin_only
def get_pending_users():
    active_dept = get_active_department()
    
    query = User.query.filter(User.is_active == False, User.role != 'ADMIN', User.department_id != None)
    
    if active_dept:
        query = query.filter(User.department_id == active_dept)
        
    pending_users = query.order_by(desc(User.created_at)).all()
    
    results = []
    for user in pending_users:
       
        if not user.department_id:
            return jsonify({
                "error": f"Data Integrity Error: Pending worker {user.first_name} ({user.phoneno}) has no department assigned."
            }), 400
            

        dept = Department.query.get(user.department_id)
        if not dept:
            return jsonify({
                "error": f"Data Integrity Error: Department ID {user.department_id} for worker {user.first_name} does not exist."
            }), 400
            
        user_dict = user.to_dict(is_admin=True) 
        user_dict['department_name'] = dept.name
        results.append(user_dict)
        
    return jsonify(results), 200    
    
@core.route('/approve-user', methods=['POST'])
@jwt_required
@admin_only
def approve_user():
    data = request.json
    target_user_id = data.get('id')
    phone = data.get('phone')
    is_approved = data.get('approved')

    # Basic validation
    if not target_user_id or phone is None or is_approved is None:
        return jsonify({"error": "Missing required fields (id, phone, approved)"}), 400

    # Fetch the pending user using both ID and phone for security
    target_user = User.query.filter_by(id=target_user_id, phoneno=phone).first()

    if not target_user:
        return jsonify({"error": "Pending user not found or phone number mismatch"}), 404

    try:
        if is_approved:
            # Activate the user so they can log in
            target_user.is_active = True
            db.session.commit()
            return jsonify({"message": f"User {target_user.first_name} has been approved."}), 200
        else:
            # Reject and delete the user so they can try registering again if needed
            db.session.delete(target_user)
            db.session.commit()
            return jsonify({"message": "User registration rejected and removed."}), 200
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Database operation failed", "details": str(e)}), 500   
 
@core.route('/users', methods=['GET'])
@jwt_required
@admin_only
def get_users():    
    # Check if a specific department was passed in the query parameters or headers
    # (Adjust this to match how get_active_department() works in your app)
    dept_id = get_active_department()
    
    query = User.query

    
    if dept_id:
        query = query.filter(User.department_id == dept_id)
        
    
    users = query.order_by(User.first_name.asc()).all()

    # Pass is_admin=True so the frontend gets the payroll configuration data
    return jsonify([user.to_dict(is_admin=True) for user in users]), 200

@core.route('/transactions', methods=['GET'])
@jwt_required
@admin_only
def get_transactions():
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    active_dept = get_active_department()

    # Base Query with eager loading via joins
    query = Transaction.query\
        .join(Product)\
        .outerjoin(Supplier)\
        .outerjoin(Contractor)\
        .filter(
            Transaction.is_active == True,
            Product.is_active == True,
            or_(Supplier.id == None, Supplier.is_active == True),
            or_(Contractor.id == None, Contractor.is_active == True)
        )
    if active_dept:
        query = query.filter(Product.department_id == active_dept)

    # Date Filters
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')
            end_date = end_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError:
            pass

    # Execute and return full list (ordered newest first)
    txns = query.order_by(desc(Transaction.created_at)).all()

    results = []
    for t in txns:
        entity_display = ""
        
        if t.type == 'in':
            entity_display = f"From: {t.supplier.name}" if t.supplier else "Supplier"
        elif t.type == 'out':
            entity_display = f"To: {t.contractor.name}" if t.contractor else "Contractor"
        elif t.type == 'return':
            if t.supplier_id:
                # You are returning defective items TO the supplier (Inventory -)
                entity_display = f"Returned to: {t.supplier.name}"
            elif t.contractor_id:
                # Contractor is returning items TO you (Inventory +)
                entity_display = f"Returned by: {t.contractor.name}"
            else:
                entity_display = "Return"

        results.append({
            "id": t.id,
            "date": t.created_at.strftime('%Y-%m-%d'),
            "type": t.type,
            "product_id": t.product_id,
            "product": t.product.name if t.product else "N/A",
            "sku": t.product.product_code if t.product else "",
            "qty": t.quantity,
            "entity": entity_display,
            "supplier_id": t.supplier_id,
            "contractor_id": t.contractor_id
        })

    return jsonify(results), 200

@core.route('/transactions/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_transaction(id):
    """
    Update Transaction Quantity.
    Automatically adjusts Product Stock based on the difference.
    """
    txn = Transaction.query.get(id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    # Permission Check
    if g.role != 'ADMIN' and txn.product.department_id != g.department_id:
         return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    try:
        new_qty = float(data.get('qty'))
        if new_qty <= 0: raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid quantity"}), 400

    product = txn.product
    old_qty = txn.quantity
    diff = new_qty - old_qty

    if diff == 0:
        return jsonify({"message": "No change detected"}), 200

    # === LOGIC: APPLY DELTA TO STOCK ===
    
    # CASE 1: STOCK IN (Supplier provided more or less)
    if txn.type == 'in' or txn.type == 'return':
        # If we increased In quantity, Stock goes UP. 
        # If we decreased In quantity, Stock goes DOWN.
        if diff < 0 and product.current_stock < abs(diff):
             return jsonify({"error": "Cannot reduce quantity: Stock would become negative"}), 400
        product.current_stock += diff

    # CASE 2: STOCK OUT (Sent to Contractor)
    elif txn.type == 'out':
        # If we increased Out quantity (sent more), Stock goes DOWN.
        # If we decreased Out quantity (sent less), Stock goes UP.
        if diff > 0 and product.current_stock < diff:
             return jsonify({"error": "Cannot increase output: Not enough stock available"}), 400
        product.current_stock -= diff

    # Update Transaction
    txn.quantity = new_qty
    
    # Log Activity
    log = ActivityLog(
        user_id=g.current_user.id, 
        action=f"Updated Txn #{txn.id} Qty: {old_qty} -> {new_qty}", 
        transaction_id=txn.id
    )
    
    db.session.add(log)
    db.session.add(product) # Save Stock Change
    
    try:
        db.session.commit()
        return jsonify({
            "message": "Transaction updated", 
            "new_stock": product.current_stock
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@core.route('/recycle-bin', methods=['GET'])
@jwt_required
@admin_only
def get_recycle_bin():
    active_dept = get_active_department() # <--- 1. Get the Context

    # --- Transactions ---
    txn_query = Transaction.query\
        .join(Product)\
        .filter(Transaction.is_active == False, Product.is_active == True)
    
    if active_dept:
        txn_query = txn_query.filter(Product.department_id == active_dept) # <--- Filter
    
    txns = txn_query.order_by(desc(Transaction.created_at)).all()
    
    # --- Products ---
    prod_query = Product.query.filter_by(is_active=False)
    if active_dept:
        prod_query = prod_query.filter_by(department_id=active_dept) # <--- Filter
    products = prod_query.all()

    # --- Suppliers ---
    sup_query = Supplier.query.filter_by(is_active=False)
    if active_dept:
        sup_query = sup_query.filter_by(department_id=active_dept) # <--- Filter
    suppliers = sup_query.all()

    # --- Contractors (Usually Global, but can be filtered if needed) ---
    contractors = Contractor.query.filter_by(is_active=False).all()
    
    return jsonify({
        "transactions": [t.to_dict() for t in txns],
        "products": [p.to_dict() for p in products],
        "suppliers": [s.to_dict() for s in suppliers],
        "contractors": [c.to_dict() for c in contractors]
    }), 200

@core.route('/recycle-bin/<string:type>/<int:id>/restore', methods=['PUT'])
@jwt_required
@admin_only
def restore_any_entity(type, id):
    
    try:
        # ====================================================
        # 1. RESTORE SUPPLIER
        # ====================================================
        if type == 'supplier':
            supplier = Supplier.query.get(id)
            if not supplier: return jsonify({"error": "Supplier not found"}), 404
            
            supplier.is_active = True
            db.session.add(supplier)
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Supplier: {supplier.name}")
            db.session.add(log)


        # ====================================================
        # 2. RESTORE CONTRACTOR
        # ====================================================
        elif type == 'contractor':
            contractor = Contractor.query.get(id)
            if not contractor: return jsonify({"error": "Contractor not found"}), 404
            
            contractor.is_active = True
            db.session.add(contractor)
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Contractor: {contractor.name}")
            db.session.add(log)


        # ====================================================
        # 3. RESTORE PRODUCT
        # ====================================================
        elif type == 'product':
            product = Product.query.get(id)
            if not product: return jsonify({"error": "Product not found"}), 404
            
            # Check if Department is active? (Optional)
            
            product.is_active = True
            db.session.add(product)
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Product: {product.name}")
            db.session.add(log)


        # ====================================================
        # 4. RESTORE TRANSACTION (Complex Logic)
        # ====================================================
        elif type == 'transaction':
            txn = Transaction.query.get(id)
            if not txn: return jsonify({"error": "Transaction not found"}), 404
            product = txn.product

            if not product or not product.is_active:
                return jsonify({"error": "Parent Product is deleted"}), 400

            # === RE-APPLY STOCK LOGIC ===
            if txn.type == 'in':
                product.current_stock += txn.quantity
            elif txn.type == 'out':
                if product.current_stock < txn.quantity:
                    return jsonify({"error": "Cannot restore: Not enough stock"}), 400
                product.current_stock -= txn.quantity
            elif txn.type == 'return':
                if txn.supplier_id:
                    # It was a return TO supplier (Stock left) -> Must subtract again
                    if product.current_stock < txn.quantity:
                        return jsonify({"error": "Cannot restore supplier return: Stock would go negative"}), 400
                    product.current_stock -= txn.quantity
                else:
                    # It was a return FROM contractor (Stock arrived) -> Must add again
                    product.current_stock += txn.quantity

            txn.is_active = True
            db.session.add(txn)
            db.session.add(product)
            
            log = ActivityLog(
                user_id=g.current_user.id, 
                action=f"Restored Transaction #{txn.id}", 
                transaction_id=txn.id
            )
            db.session.add(log)

        else:
            return jsonify({"error": "Invalid entity type"}), 400

        # Commit whatever happened above
        db.session.commit()
        return jsonify({"message": f"{type.capitalize()} restored successfully"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@core.route('/transactions/<int:id>', methods=['DELETE'])
@jwt_required
def delete_transaction(id):

    txn = Transaction.query.get(id)
    if not txn: return jsonify({"error": "Transaction not found"}), 404

    # Permission Check: Only Admin or the Department that owns the product
    if g.role != 'ADMIN' and txn.product.department_id != g.department_id:
         return jsonify({"error": "Unauthorized"}), 403

    product = txn.product

    # === REVERSE STOCK IMPACT ===
    
    if txn.type == 'in':
        if product.current_stock < txn.quantity:
             return jsonify({"error": "Cannot delete: Stock would become negative"}), 400
        product.current_stock -= txn.quantity
    elif txn.type == 'out':
        product.current_stock += txn.quantity
    elif txn.type == 'return':
        if txn.supplier_id:
            # You originally gave it away -> Deleting the record puts it BACK (+)
            product.current_stock += txn.quantity
        else:
            # Contractor originally gave it back -> Deleting the record REMOVES it (-)
            if product.current_stock < txn.quantity:
                 return jsonify({"error": "Cannot delete return: Stock would become negative"}), 400
            product.current_stock -= txn.quantity

    txn.is_active = False
    
    log = ActivityLog(
        user_id=g.current_user.id,
        action=f"Moved Txn #{txn.id} to Recycle Bin",
        transaction_id=txn.id
    )
    db.session.add(log)
    db.session.add(product)

    try:
        db.session.commit()
        return jsonify({
            "message": "Transaction moved to Recycle Bin", 
            "new_stock": product.current_stock
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500   

@core.route('/recycle-bin/<string:type>/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_permanently(type, id):
    try:
        # ====================================================
        # 1. PERMANENT DELETE CONTRACTOR
        # ====================================================
        if type == 'contractor':
            contractor = Contractor.query.get(id)
            if not contractor: 
                return jsonify({"error": "Contractor not found"}), 404

            # Get all transactions linked to this contractor
            txns = Transaction.query.filter_by(contractor_id=id).all()

            for txn in txns:
                # REVERSE THE TRANSACTION IMPACT
                if txn.product:
                    if txn.type == 'out':
                        # They took stock -> We put it back
                        txn.product.current_stock += txn.quantity
                        
                    elif txn.type == 'return':
                        # They returned stock -> We remove it (undo the return)
                        # Safety check: ensure we don't go negative
                        if txn.product.current_stock >= txn.quantity:
                            txn.product.current_stock -= txn.quantity
                        else:
                            # If we can't undo the return without going negative, 
                            # it implies the returned stock was used elsewhere.
                            # We force stock to 0 or leave it (business decision).
                            txn.product.current_stock = 0

                # Delete the transaction record
                db.session.delete(txn)

            # Finally, delete the contractor
            db.session.delete(contractor)


        # ====================================================
        # 2. PERMANENT DELETE SUPPLIER
        # ====================================================
        elif type == 'supplier':
            supplier = Supplier.query.get(id)
            if not supplier: 
                return jsonify({"error": "Supplier not found"}), 404

            # Get all 'Stock In' transactions from this supplier
            txns = Transaction.query.filter_by(supplier_id=id).all()

            products_to_delete = set()

            for txn in txns:
                if txn.product_id in products_to_delete:
                    continue # Skip if we already decided to delete this product

                if txn.product:
                    if txn.type == 'in':
                        # Logic: We are removing the record of stock arrival.
                        # So we must DEDUCT that stock from current inventory.
                        
                        if txn.product.current_stock >= txn.quantity:
                            # Scenario A: We have enough stock to just remove it.
                            txn.product.current_stock -= txn.quantity
                            db.session.delete(txn)
                        else:
                            # Scenario B: The stock provided by this supplier is already gone (sold/used).
                            # We cannot have negative stock. 
                            # Per your instruction: DELETE THE PRODUCT ITSELF.
                            products_to_delete.add(txn.product_id)

            # Process the "Corrupted" Products (where stock would have gone negative)
            for prod_id in products_to_delete:
                product = Product.query.get(prod_id)
                if product:
                    # Delete ALL transactions for this product (clean wipe)
                    Transaction.query.filter_by(product_id=prod_id).delete()
                    # Delete the product
                    db.session.delete(product)

            # Finally, delete the supplier
            db.session.delete(supplier)


        # ====================================================
        # 3. OTHER TYPES (Standard Logic)
        # ====================================================
        elif type == 'product':
            product = Product.query.get(id)
            if not product: return jsonify({"error": "Product not found"}), 404
            
            Transaction.query.filter_by(product_id=id).delete()
            db.session.delete(product)

        elif type == 'transaction':
            txn = Transaction.query.get(id)
            if not txn: return jsonify({"error": "Transaction not found"}), 404
            db.session.delete(txn)

        db.session.commit()
        return jsonify({"message": f"{type.capitalize()} permanently deleted"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/employees', methods=['GET'])
@jwt_required
@admin_only
def get_all_employees():
    employees = User.query.all()
    results = []

    
    for w in employees:

        if w.department_id is None and w.role == "ADMIN":
            continue

        dept_name = Department.query.filter_by(id = w.department_id).first()
        results.append({
            "id": w.id,
            "name": f"{w.first_name} {w.last_name}",
            "phone": w.phoneno,
            "role": w.role,
            "department": dept_name.name,
            "department_id": w.department_id,
            "is_active": w.is_active,
            "joined_at": w.created_at
        })
    return jsonify(results), 200

@core.route('/departments', methods=['GET'])
@jwt_required
def get_departments():
    depts = Department.query.filter_by(is_active=True).all()
    return jsonify([d.to_dict() for d in depts]), 200



@core.route('/employees', methods=['POST'])
@jwt_required
@admin_only
def add_employee():
    """
    Admin manually creates a Worker profile.
    Because you use Phone Auth, the worker simply logs in with this phone number 
    later, and the system will find this pre-created profile.
    """
    data = request.get_json()
    
    # 1. Validation
    if not data.get('phone') or not data.get('first_name'):
        return jsonify({"error": "Name and Phone are required"}), 400

    # 2. Check for existing user
    if User.query.filter_by(phoneno=data['phone']).first():
        return jsonify({"error": "User with this phone number already exists"}), 400

    # 3. Create User
    try:
        new_user = User(
            first_name=data['first_name'],
            last_name=data.get('last_name', ''),
            phoneno=data['phone'],
            role=data.get('role', 'WORKER'),
            department_id=data.get('department_id'),
            is_active=True # Admin created them, so they are active by default
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        return jsonify({
            "message": "Worker created successfully",
            "user": {
                "id": new_user.id,
                "name": f"{new_user.first_name} {new_user.last_name}",
                "phone": new_user.phoneno
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/employees/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_employee(id):
    """
    Update an existing worker's details (Name, Phone, Dept, Role, Status)
    """
    user = User.query.get(id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()

    # 1. Update Phone (Unique Check)
    if 'phone' in data and data['phone'] != user.phoneno:
        existing = User.query.filter_by(phoneno=data['phone']).first()
        if existing:
            return jsonify({"error": "Phone number already in use"}), 400
        user.phoneno = data['phone']

    # 2. Update Basic Info
    if 'first_name' in data: user.first_name = data['first_name']
    if 'last_name' in data: user.last_name = data['last_name']
    
    # 3. Update Role & Status
    if 'role' in data: user.role = data['role']
    if 'is_active' in data: user.is_active = bool(data['is_active'])

    # 4. Update Department
    if 'department_id' in data:
        # If frontend sends empty string or null, handle it
        if data['department_id']:
            dept = Department.query.get(data['department_id'])
            if not dept:
                return jsonify({"error": "Invalid Department ID"}), 400
            user.department_id = dept.id
        else:
            # Allow clearing department if needed (though rare for workers)
            user.department_id = None

    try:
        db.session.commit()
        return jsonify({"message": "Worker updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    

@core.route('/departments/<int:id>', methods=['GET'])
@jwt_required
def get_departments_by_id(id): 
    dept = Department.query.get(id)
    if not dept: return jsonify({"error": "Department id does not exist"}), 404
    return jsonify(dept.to_dict()), 200

@core.route('/departments', methods=['POST'])
@jwt_required
@admin_only
def add_department():
    data = request.get_json()
    unit_val = data.get('unit', 'pcs')

    if not data or 'name' not in data or 'permissions' not in data or 'unit' not in data:
        return jsonify({"error": "Name, permission or unit is required"}), 400
    
    if Department.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Department already exists"}), 400
    

    new_dept = Department(name=data['name'], unit = data['unit'], permissions=data['permissions'], is_active=True)
    db.session.add(new_dept)
    db.session.commit()
    return jsonify({"message": "Department added", "department": new_dept.to_dict()}), 201

@core.route('/departments/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_department(id): 
    dept = Department.query.get(id)

    if not dept: 
        return jsonify({"error": "Department does not exist"}, 400)
    
    data = request.get_json()

    if 'name' in data and data['name'] != dept.name: 
        existing = Department.query.filter_by(name =data['name']).first()
        if existing: 
            return jsonify({"error":"Department name already exists"}, 400)
        dept.name = data['name']

    if 'permissions' in data:
        dept.permissions = data['permissions']

    if 'is_active' in data: 
        dept.is_active = data['is_active']

    if 'unit' in data: 
        dept.unit = data['unit']    

    try:
        db.session.commit()
        return jsonify({"message": "Department updated", "department": dept.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500  


@core.route('/suppliers', methods=['POST'])
@jwt_required
def add_supplier():
    data = request.get_json()
    
    # --- 1. Basic Validation ---
    if not data.get('name'):
        return jsonify({"error": "Supplier Name is required"}), 400
        
    phone = data.get('phone')
    if phone:
        # Remove spaces/dashes to check just digits
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if len(clean_phone) != 10:
            return jsonify({"error": "Phone number must be exactly 10 digits"}), 400
    
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    # --- 2. Check Duplicate ---
    existing = Supplier.query.filter(
        Supplier.name.ilike(data['name']), 
        Supplier.department_id == active_dept
    ).first()
    
    if existing:
        if not existing.is_active:
             return jsonify({"error": "Supplier exists but is in Recycle Bin. Restore it instead."}), 400
        return jsonify({"error": "Supplier already exists"}), 400

    # --- 3. Create ---
    try:
        new_supplier = Supplier(
            name=data['name'],
            phone_number=phone, 
            department_id=active_dept,
            is_active=True
        )
        db.session.add(new_supplier)
        db.session.commit()
        
        return jsonify({
            "message": "Supplier added successfully", 
            "supplier": new_supplier.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/supplier-transactions', methods=['GET'])
@jwt_required
def supplier_transaction_report():

    # --- 1. Get Active Department ---
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    try:
        # --- 2. Query Transactions ---
        transactions = (
            db.session.query(Transaction)
            .filter(
                Transaction.department_id == active_dept,
                Transaction.type == 'in',
                Transaction.is_active == True,
                Transaction.supplier_id.isnot(None)
            )
            .order_by(Transaction.created_at.desc())
            .all()
        )

        if not transactions:
            return jsonify([]), 200

        # --- 3. Format Response ---
        result = []

        for txn in transactions:
            supplier = Supplier.query.get(txn.supplier_id)
            product = Product.query.get(txn.product_id)

            if not supplier or not product:
                continue  # Skip corrupted data safely

            result.append({
                "supplier": supplier.name,
                "supplier_id": supplier.id,
                "product": product.name,
                "product_id": product.id,
                "sku": product.product_code,
                "unit": product.unit,
                "date": txn.created_at.strftime("%Y-%m-%d"),
                "qty": txn.quantity
            })

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@core.route('/suppliers', methods=['GET'])
@jwt_required
def get_suppliers():
    # Ensure this function reads the 'X-Department-Id' header from the request
    active_dept = get_active_department() 
    
    if g.role == "ADMIN" and not active_dept:
         suppliers = Supplier.query.filter_by(is_active=True).all()
    else:
         # This forces the filter to the selected department
         suppliers = Supplier.query.filter_by(is_active=True, department_id=active_dept).all()
    
    return jsonify([s.to_dict() for s in suppliers]), 200

@core.route('/suppliers/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_supplier(id):
    supplier = Supplier.query.get(id)
    if not supplier:
        return jsonify({"error": "Supplier not found"}), 404

    data = request.get_json()
    
    if 'name' in data: supplier.name = data['name']
    if 'phone' in data: supplier.phone_number = data['phone'] # Assuming column is phone_number
    
    try:
        db.session.commit()
        return jsonify({"message": "Supplier updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/contractors/<int:id>', methods=['PUT'])
@jwt_required
def update_contractor(id):
    contractor = Contractor.query.get(id)
    if not contractor:
        return jsonify({"error": "Contractor not found"}), 404

    data = request.get_json()
    
    if 'name' in data: contractor.name = data['name']
    # Add other fields if your Contractor model has them (e.g. phone, address)

    try:
        db.session.commit()
        return jsonify({"message": "Contractor updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@core.route('/contractors', methods=['GET'])
@jwt_required
def get_contractors():
    # Only allowed for specific departments usually, or everyone?
    # Keeping logic simple based on previous code.
    contractors = Contractor.query.filter_by(is_active=True).all()
    return jsonify([c.to_dict() for c in contractors]), 200

@core.route('/contractors', methods=['POST'])
@jwt_required
def add_contractor():
    data = request.get_json()

    # --- 1. Basic Validation ---
    if not data.get('name'):
        return jsonify({"error": "Contractor Name is required"}), 400

    phone = data.get('phone')
    if phone:
        # Remove spaces/dashes to check just digits
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if len(clean_phone) != 10:
            return jsonify({"error": "Phone number must be exactly 10 digits"}), 400

    # --- 2. Check Duplicate ---
    existing = Contractor.query.filter(Contractor.name.ilike(data['name'])).first()
    
    if existing:
        if not existing.is_active:
             return jsonify({"error": "Contractor exists but is in Recycle Bin. Restore it instead."}), 400
        return jsonify({"error": "Contractor already exists"}), 400

    # --- 3. Create ---
    try:
        new_contractor = Contractor(
            name=data['name'],
            phone=phone, 
            is_active=True
        )
        db.session.add(new_contractor)
        db.session.commit()
        
        return jsonify({
            "message": "Contractor added successfully", 
            "contractor": new_contractor.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    


@core.route('/products', methods=['POST'])
@jwt_required
def add_product():
    data = request.get_json()
    sku = data.get('sku')
    
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    new_p = Product(
        name=data['name'],
        product_code=sku,
        category=data.get('category'),
        current_stock=0,
        department_id=active_dept,
        is_active=True
    )
    db.session.add(new_p)
    db.session.commit()
    return jsonify({"message": "Product created"}), 201


@core.route('/products/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_product(id):

    active_department = get_active_department()
    product = Product.query.get(id)
    if not product: 
        return jsonify({"error": "Product does not exist"}, 404)
    
    if active_department and product.department_id != active_department: 
        return jsonify({"error": "Department Id does not match with product department id"}, 403)
    
    
    if product.is_active is False: 
        return jsonify({"error":"Product has already been deleted from frontend"}, 400)
    
    product.is_active = False

    try:
        db.session.commit()
        return jsonify({"message": "Product was successfully deleted from frontend"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    

@core.route('/suppliers/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_suppliers(id): 
    supplier = Supplier.query.get(id)
    active_dept = get_active_department()

    if not supplier: 
        return jsonify({"error": "Supplier does not exist"}, 404)
    
    if active_dept and supplier.department_id != active_dept: 
        return jsonify({"error": "User is not Authorized to make this action"}, 401)
    

    if supplier.is_active == False: 
        return jsonify({"error": "Supplier is already inactive"}, 400)
    
    
    
    supplier.is_active = False

    try: 
        db.session.commit()
        return jsonify({"message": "Supplier successfully removed"}, 200)
    
    except Exception as e: 
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    
@core.route('/contractors/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_contractor(id): 
    contractor = Contractor.query.get(id)

    if not contractor: 
        return jsonify({"error": "Contractor does not exist"}), 404
    
    # --- Department Check (Optional) ---
    # Only enable this if your Contractor model has a 'department_id' column
    # if active_dept and contractor.department_id != active_dept: 
    #     return jsonify({"error": "User is not Authorized to make this action"}, 401)
    
    if contractor.is_active == False: 
        return jsonify({"error": "Contractor is already inactive"}), 400
    
    contractor.is_active = False

    try: 
        db.session.commit()
        return jsonify({"message": "Contractor successfully removed"}), 200
    
    except Exception as e: 
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    

@core.route('/contractors/<int:id>/stock', methods=['GET'])
@jwt_required
def get_contractor_stock(id):
    results = db.session.query(
        Product.id,
        Product.name,
        Product.product_code,
        Product.unit,
        func.sum(case(
            (Transaction.type == 'out', Transaction.quantity), 
            (Transaction.type == 'return', -Transaction.quantity), # Subtract returns
            else_=0
        )).label('net_qty')
    ).join(Transaction)\
     .filter(
         Transaction.contractor_id == id, 
         Transaction.is_active == True  # ✅ CRITICAL FIX: Ignore deleted transactions
     )\
     .group_by(Product.id, Product.name, Product.product_code, Product.unit)\
     .having(func.sum(case(
            (Transaction.type == 'out', Transaction.quantity),
            (Transaction.type == 'return', -Transaction.quantity),
            else_=0
        )) > 0)\
     .all()

    stock_list = []
    for r in results:
        stock_list.append({
            "product_id": r.id,
            "product_name": r.name,
            "sku": r.product_code,
            "unit": r.unit,
            "qty": r.net_qty
        })
    return jsonify(stock_list), 200

# @core.route("/suppliers/<int:id>/products", methods=["GET"])
# @jwt_required
# def get_supplier_products(id): 
#     try:
#         # Check if we need drill-down data
#         product_id = request.args.get('product_id')

#         # --- MODE 1: Drill Down (Transaction History) ---
#         if product_id:
#             transactions = Transaction.query.filter(
#                 Transaction.supplier_id == id,
#                 Transaction.product_id == product_id,
#                 # Using lower() ensures case-insensitivity ('IN', 'in')
#                 func.lower(Transaction.type) == 'in'
#             ).order_by(Transaction.created_at.desc()).all()

#             return jsonify([t.to_dict() for t in transactions]), 200

#         # --- MODE 2: Consolidated View (Main Table) ---
#         results = db.session.query(
#             Product.id,  # Need ID for the drill-down link
#             Product.name,
#             Product.product_code,
#             func.sum(Transaction.quantity).label('total_supplied'),
#             func.max(Transaction.created_at).label('last_supplied')
#         ).join(Transaction, Transaction.product_id == Product.id)\
#          .filter(
#              Transaction.supplier_id == id,
#              func.lower(Transaction.type) == 'in'
#          )\
#          .group_by(Product.id)\
#          .all()

#         data = []
#         for r in results:
#             data.append({
#                 "id": r.id,
#                 "name": r.name,
#                 "sku": r.product_code,
#                 "total_supplied": r.total_supplied,
#                 "last_supplied": r.last_supplied.strftime('%Y-%m-%d') if r.last_supplied else "N/A"
#             })

#         return jsonify(data), 200

#     except Exception as e:
#         print(f"Error: {e}")
#         return jsonify({"error": "Failed to fetch supplier data"}), 500

@core.route("/suppliers/<int:id>/products", methods=["GET"])
@jwt_required
def get_supplier_products(id): 
    try:
        product_id = request.args.get('product_id')

        # --- MODE 1: Drill Down (Transaction History) ---
        if product_id:
            # We now fetch both 'in' and 'return' so the history modal shows everything
            transactions = Transaction.query.filter(
                Transaction.supplier_id == id,
                Transaction.product_id == product_id,
                func.lower(Transaction.type).in_(['in', 'return'])
            ).order_by(Transaction.created_at.desc()).all()

            return jsonify([t.to_dict() for t in transactions]), 200

        # --- MODE 2: Consolidated View (Main Table) ---
        # We use a case statement to subtract 'return' from 'in'
        results = db.session.query(
            Product.id,
            Product.name,
            Product.product_code,
            func.sum(
                db.case(
                    (func.lower(Transaction.type) == 'in', Transaction.quantity),
                    (func.lower(Transaction.type) == 'return', -Transaction.quantity),
                    else_=0
                )
            ).label('total_supplied'),
            func.max(Transaction.created_at).label('last_supplied')
        ).join(Transaction, Transaction.product_id == Product.id)\
         .filter(
             Transaction.supplier_id == id,
             func.lower(Transaction.type).in_(['in', 'return'])
         )\
         .group_by(Product.id)\
         .all()

        data = []
        for r in results:
            data.append({
                "id": r.id,
                "name": r.name,
                "sku": r.product_code,
                "total_supplied": float(r.total_supplied or 0), # Ensure it's a number
                "last_supplied": r.last_supplied.strftime('%Y-%m-%d') if r.last_supplied else "N/A"
            })

        return jsonify(data), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

@core.route('/products/<int:id>/transactions', methods=['GET'])
@jwt_required
def get_product_transactions(id):
    # 1. Product Existence Check
    product = Product.query.get(id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    # OPTIMIZED: Add pagination
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    per_page = min(per_page, 10000)  # Cap at 100

    # 2. Get Date Filters from Query Params
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    # 3. Build Base Query (Identical to get_transactions, but filtered by ID)
    query = Transaction.query\
        .join(Product)\
        .outerjoin(Supplier)\
        .outerjoin(Contractor)\
        .filter(
            Transaction.product_id == id,  # 👈 Specific Product Filter
            Transaction.is_active == True,
            Product.is_active == True,
            or_(Supplier.id == None, Supplier.is_active == True),
            or_(Contractor.id == None, Contractor.is_active == True)
        )

    # 4. Apply Date Filters
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')
            # Ensure we cover the full end day
            end_date = end_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError:
            pass

    # 5. Execute with pagination
    paginated = query.order_by(desc(Transaction.created_at)).paginate(page=page, per_page=per_page, error_out=False)

    # 6. Format Results (Exact match to Global History)
    results = []
    for t in paginated.items:
        entity_name = "Manual Adjustment"
        if t.type == 'in' and t.supplier:
            entity_name = f"Supplier: {t.supplier.name}"
        elif t.type == 'out' and t.contractor:
            entity_name = f"Contractor: {t.contractor.name}"
        elif t.type == 'return' and t.contractor:
            entity_name = f"Returned by: {t.contractor.name}"
        elif t.type == 'return' and t.supplier:
            entity_name = f"Returned to: {t.supplier.name}"   

        results.append({
            "id": t.id,
            "date": t.created_at.strftime('%Y-%m-%d'),
            "type": t.type,
            "product_id": t.product_id,
            "product": t.product.name,
            "sku": t.product.product_code,
            "qty": t.quantity,
            "entity": entity_name,
            "is_active": t.is_active,
            "supplier_id": t.supplier_id,
            "contractor_id": t.contractor_id
        })

    return jsonify({
        "data": results,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": paginated.total,
            "pages": paginated.pages
        }
    }), 200