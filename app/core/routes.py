from flask import Blueprint, jsonify, request, g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.extensions import db
from sqlalchemy import func, case, desc
from datetime import datetime, date
import calendar
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, and_

# Import ALL models
from app.models.department import Department
from app.models.supplier import Supplier
from app.models.contractor import Contractor
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.user import User  
from app.models.activity_log import ActivityLog
from app.models.attendance import Attendance
from app.models.category import Category
from app.models.subcategory import SubCategory
from app.models.categorysuborder import CategorySubOrder

core = Blueprint('core', __name__, url_prefix='/core')


def get_active_department():
    # Admins can "impersonate" departments via headers
    if g.role == "ADMIN":
        try:
            dept_id = request.headers.get("X-Department-Id")
            return int(dept_id) if dept_id else None
        except ValueError:
            return None
            
    # ✅ Workers always use their latest database-assigned department
    return g.current_user.department_id


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
            # category=data.get('category', 'General'),
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

    if op_type == 'in':
        sup_name = data.get('supplier_name', '').strip()
        if not sup_name and not supplier_id:
            return jsonify({"error": "Supplier Name is strictly required to add stock."}), 400
            
        product.current_stock += qty
        
        if not supplier_id:
            supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
            if not supplier: # 👇 Now nested correctly inside 'if not supplier_id'
                supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
                db.session.add(supplier)
                db.session.flush()
            supplier_id = supplier.id
        
    elif op_type == 'out':
        cont_name = data.get('contractor_name', '').strip()
        if not cont_name and not contractor_id:
            return jsonify({"error": "Contractor Name is strictly required to issue stock."}), 400
            
        if product.current_stock < qty:
            return jsonify({"error": f"Insufficient stock ({product.current_stock})"}), 400
        product.current_stock -= qty
        
        if not contractor_id:
            contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
            if not contractor: # 👇 Now nested correctly inside 'if not contractor_id'
                contractor = Contractor(name=cont_name, is_active=True)
                db.session.add(contractor)
                db.session.flush()
            contractor_id = contractor.id

    elif op_type == 'return':
        sup_name = data.get('supplier_name', '').strip()
        cont_name = data.get('contractor_name', '').strip()

        if not sup_name and not cont_name and not supplier_id and not contractor_id:
             return jsonify({"error": "A Supplier or Contractor is strictly required to process a return."}), 400
        
        if sup_name or supplier_id:
            if product.current_stock < qty:
                return jsonify({"error": f"Insufficient stock to return. Current: {product.current_stock}"}), 400
            product.current_stock -= qty
            
            if not supplier_id:
                supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
                if not supplier: # 👇 Nested correctly
                    supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
                    db.session.add(supplier)
                    db.session.flush()
                supplier_id = supplier.id

        elif cont_name or contractor_id:
            product.current_stock += qty  
            if not contractor_id:
                contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
                if not contractor: # 👇 Nested correctly
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
            department_id=worker.department_id,
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
# @core.route('/products', methods=['GET'])
# @jwt_required
# def get_products():
#     active_dept = get_active_department()
#     if not active_dept:
#         return jsonify({"error": "Department context missing"}), 400

#     products = Product.query.filter_by(
#         is_active=True,
#         department_id=active_dept
#     ).all()

#     return jsonify([p.to_dict() for p in products]), 200
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import joinedload # 👈 Ensure this is imported at the top

@core.route('/products', methods=['GET'])
@jwt_required
def get_products():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    # IF FILTER IS ACTIVE:
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            
            results = db.session.query(
                Product,
                func.sum(case(((Transaction.type == 'in'), Transaction.quantity),
                              (and_(Transaction.type == 'return', Transaction.supplier_id == None), Transaction.quantity), else_=0)).label('t_in'),
                func.sum(case(((Transaction.type == 'out'), Transaction.quantity),
                              (and_(Transaction.type == 'return', Transaction.supplier_id != None), Transaction.quantity), else_=0)).label('t_out')
            ).options(
                # 👇 THIS IS THE MAGIC THAT FIXES THE 9-SECOND DELAY
                joinedload(Product.category_rel),
                joinedload(Product.sub_category_rel)
            ).outerjoin(Transaction, and_(
                Transaction.product_id == Product.id, 
                Transaction.is_active == True,
                Transaction.created_at.between(start_date, end_date)
            )).filter(
                Product.department_id == active_dept, 
                Product.is_active == True
            ).group_by(Product.id).all()

            data = []
            for p, t_in, t_out in results:
                p_dict = p.to_dict()
                p_dict['total_stock_in'] = float(t_in or 0)
                p_dict['total_stock_out'] = float(t_out or 0)
                data.append(p_dict)
            return jsonify(data), 200
        except ValueError:
            pass

    # ALL TIME DATA (NO DATE FILTER):
    # 👇 ADD JOINEDLOAD HERE AS WELL!
    products = Product.query.options(
        joinedload(Product.category_rel),
        joinedload(Product.sub_category_rel)
    ).filter_by(
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
        product = Product.query.get(id)
        if not product: 
            return jsonify({"error": "Product not found"}), 404

        active_dept = get_active_department()
        if g.role != 'ADMIN' and product.department_id != active_dept:
            return jsonify({"error": "Unauthorized"}), 403

        data = request.get_json()
        
        # 🛡️ VALIDATE NAME
        if 'name' in data:
            new_name = data['name']
            if not new_name or not str(new_name).strip():
                return jsonify({"error": "Product name cannot be empty."}), 400
            product.name = str(new_name).strip()

        # 🛡️ VALIDATE SKU
        if 'sku' in data:
            new_sku = data['sku']
            if not new_sku or not str(new_sku).strip():
                return jsonify({"error": "Product SKU cannot be empty."}), 400
            new_sku = str(new_sku).strip()
            if new_sku != product.product_code:
                product.product_code = new_sku
        
        # 🛑 VALIDATE MIN STOCK (No Negatives)
        if 'min_stock' in data: 
            try: 
                val = data['min_stock']
                if val == "" or val is None:
                    product.min_stock = 0.0
                else:
                    parsed_val = float(val)
                    if parsed_val < 0: return jsonify({"error": "Min stock cannot be negative."}), 400
                    product.min_stock = parsed_val
            except ValueError: 
                return jsonify({"error": "Invalid number for min stock."}), 400
        
        # 🛑 VALIDATE MAX STOCK (No Negatives)
        if 'max_stock' in data:
            try: 
                val = data['max_stock']
                if val == "" or val is None:
                    product.max_stock = 0.0
                else:
                    parsed_val = float(val)
                    if parsed_val < 0: return jsonify({"error": "Max stock cannot be negative."}), 400
                    product.max_stock = parsed_val
            except ValueError: 
                return jsonify({"error": "Invalid number for max stock."}), 400 

        if 'category_name' in data:
            cat_name = data['category_name'].strip().upper()
            if cat_name:
                category = Category.query.filter_by(name=cat_name).first()
                if not category:
                    category = Category(name=cat_name)
                    db.session.add(category)
                    db.session.flush() 
                product.category_id = category.id

        if 'sub_category_name' in data:
            sub_name = data['sub_category_name'].strip().upper()
            if sub_name:
                sub_cat = SubCategory.query.filter_by(name=sub_name).first()
                if not sub_cat:
                    sub_cat = SubCategory(name=sub_name)
                    db.session.add(sub_cat)
                    db.session.flush() 
                product.sub_category_id = sub_cat.id

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
    
    query = User.query.filter(User.approval_status != 'APPROVED', User.role != 'ADMIN')
    
    if active_dept:
        query = query.filter(User.department_id == active_dept)
        
    pending_users = query.order_by(desc(User.created_at)).all()
    
    results = []
    for user in pending_users:
        user_dict = user.to_dict(is_admin=True)
        user_dict['approval_status'] = user.approval_status
        user_dict['requested_department_id'] = user.requested_department_id
        
        # For current department
        if user.department_id:
            dept = Department.query.get(user.department_id)
            user_dict['department_name'] = dept.name if dept else "Unknown"
        
        # For requested department (dept change case)
        if user.requested_department_id:
            req_dept = Department.query.get(user.requested_department_id)
            user_dict['requested_department_name'] = req_dept.name if req_dept else "Unknown"
        
        results.append(user_dict)
        
    return jsonify(results), 200   
    
@core.route('/approve-user', methods=['POST'])
@jwt_required
def approve_user():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    target_user_id = data.get('id')
    phone = data.get('phone')
    is_approved = data.get('approved')

    # 👇 FIXED VALIDATION: Explicitly check for None
    if target_user_id is None or phone is None or is_approved is None:
        return jsonify({
            "error": "Missing required fields (id, phone, approved)",
            "received": data # 👈 This helps you debug if the frontend sent bad data
        }), 400

    target_user = User.query.filter_by(id=target_user_id, phoneno=phone).first()

    if not target_user:
        return jsonify({"error": "Pending user not found or phone number mismatch"}), 404

    try:
        if is_approved:
            # CASE 1: New Signup Approval
            if target_user.approval_status == 'PENDING_SIGNUP':
                target_user.is_active = True
                target_user.approval_status = 'APPROVED'
                db.session.commit()
                return jsonify({"message": f"User {target_user.first_name} has been approved."}), 200
            
            # CASE 2: Department Change Approval
            elif target_user.approval_status == 'PENDING_DEPT_CHANGE':
                if not target_user.requested_department_id:
                    return jsonify({"error": "No department change request found"}), 400
                
                target_user.department_id = target_user.requested_department_id
                target_user.requested_department_id = None
                target_user.approval_status = 'APPROVED'
                target_user.is_active = True
                db.session.commit()
                return jsonify({"message": f"Department change for {target_user.first_name} has been approved."}), 200
            
            else:
                return jsonify({"error": "User is already approved"}), 400
        
        else:
 
            if target_user.approval_status == 'PENDING_SIGNUP':
                db.session.delete(target_user)
                db.session.commit()
                return jsonify({"message": "User registration rejected and removed."}), 200
            
            # CASE 2: Reject department change - revert to old status
            elif target_user.approval_status == 'PENDING_DEPT_CHANGE':
                target_user.requested_department_id = None
                target_user.approval_status = 'APPROVED'
                
                # ✅ ADD THIS: Unlock the user so they can use their OLD department
                target_user.is_active = True 
                
                db.session.commit()
                return jsonify({"message": "Department change rejected. User reverted to original department."}), 200
            
            else:
                return jsonify({"error": "Cannot reject already approved user"}), 400
            
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

    # 👇 ADD .options() HERE
    query = Transaction.query.options(
        joinedload(Transaction.product),
        joinedload(Transaction.supplier),
        joinedload(Transaction.contractor)
    ).join(Product)\
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
    active_dept = get_active_department()

    # --- Transactions ---
    # 👇 ADD .options() HERE
    txn_query = Transaction.query.options(
        joinedload(Transaction.product),
        joinedload(Transaction.supplier),
        joinedload(Transaction.contractor)
    ).join(Product).filter(Transaction.is_active == False, Product.is_active == True)
    
    if active_dept:
        txn_query = txn_query.filter(Product.department_id == active_dept)
        
    txns = txn_query.order_by(desc(Transaction.created_at)).all()
    
    # --- Products ---
    # 👇 ADD .options() HERE
    prod_query = Product.query.options(
        joinedload(Product.category_rel),
        joinedload(Product.sub_category_rel)
    ).filter_by(is_active=False)
    
    if active_dept:
        prod_query = prod_query.filter_by(department_id=active_dept)
        
    products = prod_query.all()

    # --- Suppliers ---
    sup_query = Supplier.query.filter_by(is_active=False)
    if active_dept:
        sup_query = sup_query.filter_by(department_id=active_dept) # <--- Filter
    suppliers = sup_query.all()

    # --- Contractors (Usually Global, but can be filtered if needed) ---
    contractors = Contractor.query.filter_by(is_active=False).all()

    categories = Category.query.filter_by(is_active=False).all()
    sub_categories = SubCategory.query.filter_by(is_active=False).all()
    
    return jsonify({
        "transactions": [t.to_dict() for t in txns],
        "products": [p.to_dict() for p in products],
        "suppliers": [s.to_dict() for s in suppliers],
        "contractors": [c.to_dict() for c in contractors],
        "categories": [c.to_dict() for c in categories], # 👈
        "sub_categories": [s.to_dict() for s in sub_categories] # 👈
    }), 200
    
    

@core.route('/recycle-bin/<string:type>/<int:id>/restore', methods=['PUT'])
@jwt_required
@admin_only
def restore_any_entity(type, id):
    try:
        # ====================================================
        # 1. RESTORE SUPPLIER & CASCADE RESTORE TRANSACTIONS
        # ====================================================
        if type == 'supplier':
            supplier = Supplier.query.get(id)
            if not supplier: return jsonify({"error": "Supplier not found"}), 404
            
            supplier.is_active = True
            db.session.add(supplier)
            
            # Find and restore all their deleted transactions
            txns = Transaction.query.filter_by(supplier_id=id, is_active=False).all()
            for txn in txns:
                # Only adjust stock if the product wasn't permanently deleted
                if txn.product and txn.product.is_active:
                    if txn.type == 'in':
                        txn.product.current_stock += txn.quantity # Put the stock back
                    elif txn.type == 'return':
                        if txn.product.current_stock < txn.quantity:
                            return jsonify({"error": f"Cannot restore supplier: Not enough stock of '{txn.product.name}' to re-apply past returns."}), 400
                        txn.product.current_stock -= txn.quantity # Take the returned stock out again
                
                txn.is_active = True
                db.session.add(txn)

            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Supplier & Transactions: {supplier.name}"[:50])
            db.session.add(log)


        # ====================================================
        # 2. RESTORE CONTRACTOR & CASCADE RESTORE TRANSACTIONS
        # ====================================================
        elif type == 'contractor':
            contractor = Contractor.query.get(id)
            if not contractor: return jsonify({"error": "Contractor not found"}), 404
            
            contractor.is_active = True
            db.session.add(contractor)
            
            # Find and restore all their deleted transactions
            txns = Transaction.query.filter_by(contractor_id=id, is_active=False).all()
            for txn in txns:
                if txn.product and txn.product.is_active:
                    if txn.type == 'out':
                        if txn.product.current_stock < txn.quantity:
                            return jsonify({"error": f"Cannot restore contractor: Not enough stock of '{txn.product.name}' to re-apply past outputs."}), 400
                        txn.product.current_stock -= txn.quantity # Deduct the stock they took
                    elif txn.type == 'return':
                        txn.product.current_stock += txn.quantity # Add the stock they returned back
                
                txn.is_active = True
                db.session.add(txn)

            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Contractor & Transactions: {contractor.name}"[:50])
            db.session.add(log)


        # ====================================================
        # 3. RESTORE PRODUCT
        # ====================================================
        elif type == 'product':
            product = Product.query.get(id)
            if not product: return jsonify({"error": "Product not found"}), 404
            
            product.is_active = True
            db.session.add(product)
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Product: {product.name}"[:50])
            db.session.add(log)


        # ====================================================
        # 4. RESTORE TRANSACTION (Complex Logic)
        # ====================================================
        elif type == 'transaction':
            txn = Transaction.query.get(id)
            if not txn: return jsonify({"error": "Transaction not found"}), 404
            product = txn.product

            if not product or not product.is_active:
                return jsonify({"error": "Cannot restore: Parent Product is deleted"}), 400

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
                action=f"Restored Transaction #{txn.id}"[:50], 
                transaction_id=txn.id
            )
            db.session.add(log)

        elif type == 'category':
            cat = Category.query.get(id)
            if not cat: return jsonify({"error": "Category not found"}), 404
            cat.is_active = True
            db.session.add(cat)
            
        elif type == 'sub_category':
            sub = SubCategory.query.get(id)
            if not sub: return jsonify({"error": "Sub-Category not found"}), 404
            sub.is_active = True
            db.session.add(sub)

        else:
            return jsonify({"error": "Invalid entity type"}), 400

        # Commit whatever happened above
        db.session.commit()
        return jsonify({"message": f"{type.replace('_', '-').title()} restored successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/transactions/<int:id>', methods=['DELETE'])
@jwt_required
def delete_transaction(id):
    """
    Soft-deletes a transaction (moves to Recycle Bin) and accurately 
    reverses its historical impact on the current product stock.
    """
    txn = Transaction.query.get(id)
    if not txn: 
        return jsonify({"error": "Transaction not found"}), 404

    # Permission Check: Only Admin or the Department that owns the product
    active_dept = get_active_department()
    if g.role != 'ADMIN' and txn.product.department_id != active_dept:
         return jsonify({"error": "Unauthorized to delete this transaction"}), 403

    product = txn.product

    # ==========================================
    # REVERSE STOCK IMPACT
    # ==========================================
    if txn.type == 'in':
        # It was originally added. So we must subtract it.
        if product.current_stock < txn.quantity:
             return jsonify({"error": "Cannot delete: Stock would become negative"}), 400
        product.current_stock -= txn.quantity
        
    elif txn.type == 'out':
        # It was originally subtracted. So we must add it back.
        product.current_stock += txn.quantity
        
    elif txn.type == 'return':
        if txn.supplier_id:
            # Return TO supplier (Stock originally went down). We must add it back.
            product.current_stock += txn.quantity
        else:
            # Return FROM contractor (Stock originally went up). We must subtract it.
            if product.current_stock < txn.quantity:
                 return jsonify({"error": "Cannot delete return: Stock would become negative"}), 400
            product.current_stock -= txn.quantity

    # 1. Soft Delete the transaction
    txn.is_active = False

    # 2. Log the activity
    log = ActivityLog(
        user_id=g.current_user.id,
        action=f"Moved Txn #{txn.id} to Recycle Bin",
        transaction_id=txn.id
    )
    
    # 3. Stage changes
    db.session.add(log)
    db.session.add(product)

    # 4. Commit to database
    try:
        db.session.commit()
        return jsonify({
            "message": "Transaction moved to Recycle Bin", 
            "new_stock": product.current_stock
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500


@core.route('/recycle-bin/<string:type>/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_permanently(type, id):
    try:
        # 1. PERMANENT DELETE CONTRACTOR
        if type == 'contractor':
            contractor = Contractor.query.get(id)
            if not contractor: return jsonify({"error": "Contractor not found"}), 404

            txns = Transaction.query.filter_by(contractor_id=id).all()
            for txn in txns:
                ActivityLog.query.filter_by(transaction_id=txn.id).delete() # 👈 Fixes FK Crash
                db.session.delete(txn)
            
            db.session.delete(contractor)

        # 2. PERMANENT DELETE SUPPLIER
        elif type == 'supplier':
            supplier = Supplier.query.get(id)
            if not supplier: return jsonify({"error": "Supplier not found"}), 404

            txns = Transaction.query.filter_by(supplier_id=id).all()
            for txn in txns:
                ActivityLog.query.filter_by(transaction_id=txn.id).delete() # 👈 Fixes FK Crash
                db.session.delete(txn)
            
            db.session.delete(supplier)

        # 3. PERMANENT DELETE PRODUCT
        elif type == 'product':
            product = Product.query.get(id)
            if not product: return jsonify({"error": "Product not found"}), 404
            
            txns = Transaction.query.filter_by(product_id=id).all()
            for txn in txns:
                ActivityLog.query.filter_by(transaction_id=txn.id).delete() # 👈 Fixes FK Crash
                db.session.delete(txn)
                
            db.session.delete(product)

        # 4. PERMANENT DELETE TRANSACTION
        elif type == 'transaction':
            txn = Transaction.query.get(id)
            if not txn: return jsonify({"error": "Transaction not found"}), 404
            
            ActivityLog.query.filter_by(transaction_id=txn.id).delete() # 👈 Fixes FK Crash
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
            "approval_status": w.approval_status,
            "requested_department_id": w.requested_department_id,
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
            role=data.get('role', 'USER'),
            department_id=data.get('department_id'),
            is_active=True,
            approval_status='APPROVED'  # Admin created = auto-approved
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
    active_dept = get_active_department()

    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    # 🛡️ VALIDATE NAME
    name = data.get('name')
    if not name or not str(name).strip():
        return jsonify({"error": "Supplier Name is required and cannot be empty."}), 400
    name = str(name).strip()
        
    phone = data.get('phone')
    clean_phone = None
    if phone:
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if len(clean_phone) != 10:
            return jsonify({"error": "Phone number must be exactly 10 digits"}), 400

    try:
        existing = Supplier.query.filter(
            Supplier.name.ilike(name), 
            Supplier.department_id == active_dept
        ).first()
        
        if existing:
            if not existing.is_active:
                 return jsonify({"error": "Supplier exists but is in Recycle Bin. Restore it instead."}), 400
            return jsonify({"error": "Supplier already exists"}), 400

        new_supplier = Supplier(
            name=name,
            phone_number=clean_phone, 
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
        return jsonify({"error": "Failed to add supplier", "details": str(e)}), 500
    
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
    
    # 🛡️ VALIDATE NAME
    if 'name' in data: 
        new_name = data['name']
        if not new_name or not str(new_name).strip():
            return jsonify({"error": "Supplier name cannot be empty."}), 400
        supplier.name = str(new_name).strip()
        
    if 'phone' in data: supplier.phone_number = data['phone'] 
    
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
    
    # 🛡️ VALIDATE NAME
    if 'name' in data: 
        new_name = data['name']
        if not new_name or not str(new_name).strip():
            return jsonify({"error": "Contractor name cannot be empty."}), 400
        contractor.name = str(new_name).strip()

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

    # 🛡️ VALIDATE NAME
    name = data.get('name')
    if not name or not str(name).strip():
        return jsonify({"error": "Contractor Name is required and cannot be empty."}), 400
    name = str(name).strip()

    phone = data.get('phone')
    clean_phone = None
    if phone:
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        if len(clean_phone) != 10:
            return jsonify({"error": "Phone number must be exactly 10 digits"}), 400

    try:
        existing = Contractor.query.filter(Contractor.name.ilike(name)).first()
        
        if existing:
            if not existing.is_active:
                 return jsonify({"error": "Contractor exists but is in Recycle Bin. Restore it instead."}), 400
            return jsonify({"error": "Contractor already exists"}), 400

        new_contractor = Contractor(
            name=name,
            phone=clean_phone, 
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
        return jsonify({"error": "Failed to add contractor", "details": str(e)}), 500

@core.route('/categories', methods=['GET'])
@jwt_required
def get_categories():
    cats = Category.query.order_by(Category.display_order.asc(), Category.id.asc()).all()
    
    result = []
    for c in cats:
        sub_orders_query = CategorySubOrder.query.filter_by(category_id=c.id).all()
        sub_orders_dict = {str(so.sub_category_id): so.display_order for so in sub_orders_query}
        
        result.append({
            "id": c.id, 
            "name": c.name, 
            "display_order": c.display_order,
            "sub_orders": sub_orders_dict
        })
    return jsonify(result), 200

@core.route('/categories/reorder', methods=['PUT'])
@jwt_required
def reorder_categories():
    data = request.get_json() 
    # data is exactly what we need: [{'id': 1, 'display_order': 2}, ...]
    
    # This executes a single bulk UPDATE statement, completely bypassing the SELECT loop
    db.session.bulk_update_mappings(Category, data)
    db.session.commit()
    
    return jsonify({"message": "Category order updated"}), 200

@core.route('/sub-categories/reorder', methods=['PUT'])
@jwt_required
def reorder_sub_categories():
    data = request.get_json()
    
    db.session.bulk_update_mappings(SubCategory, data)
    db.session.commit()
    
    return jsonify({"message": "Sub-Category order updated"}), 200

# --- UPDATED ADD PRODUCT ---

# 1. Update the Main Category Swap
@core.route('/categories/swap', methods=['PUT'])
@jwt_required
def swap_categories():
    data = request.get_json()
    cat1 = Category.query.get(data['id1'])
    cat2 = Category.query.get(data['id2'])

    if cat1 and cat2:
        # 👇 Perform a true swap using the database's existing values
        cat1.display_order, cat2.display_order = cat2.display_order, cat1.display_order
        
        db.session.commit()
        return jsonify({"message": "Items swapped successfully"}), 200
        
    return jsonify({"error": "Items not found"}), 404


@core.route('/categories/<int:category_id>/sub-categories/swap', methods=['PUT'])
@jwt_required
def swap_contextual_sub_categories(category_id):
    data = request.get_json()
    sub_id1 = data['id1']
    sub_id2 = data['id2']
    order1 = data['order1'] # 👈 Take explicit numbers from frontend
    order2 = data['order2']
    
    def update_or_create(sub_id, order_value):
        mapping = CategorySubOrder.query.filter_by(category_id=category_id, sub_category_id=sub_id).first()
        if not mapping:
            mapping = CategorySubOrder(category_id=category_id, sub_category_id=sub_id)
            db.session.add(mapping)
        mapping.display_order = order_value # 👈 Force the exact number
        return mapping

    update_or_create(sub_id1, order1)
    update_or_create(sub_id2, order2)
    
    db.session.commit()
    return jsonify({"message": "Contextual swap successful"}), 200

@core.route('/sub-categories/swap', methods=['PUT'])
@jwt_required
def swap_sub_categories():
    data = request.get_json()
    item1 = SubCategory.query.get(data['id1'])
    item2 = SubCategory.query.get(data['id2'])

    if item1 and item2:
        item1.display_order, item2.display_order = item2.display_order, item1.display_order
        db.session.commit()
        return jsonify({"message": "Items swapped successfully"}), 200
        
    return jsonify({"error": "Items not found"}), 404

@core.route('/categories', methods=['POST'])
@jwt_required
def add_category():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Category name is required"}), 400
        
    new_cat = Category(
        name=data['name'], 
        display_order=data.get('display_order', 0),
        is_active=True  # 👈 Added this to support your new Recycle Bin logic
        # 💥 Removed match_codes
    )
    db.session.add(new_cat)
    db.session.commit()
    return jsonify({"message": "Category added successfully", "id": new_cat.id}), 201


@core.route('/categories/<int:cat_id>', methods=['DELETE'])
@jwt_required
def delete_category(cat_id):
    cat = Category.query.get(cat_id)
    if not cat:
        return jsonify({"error": "Category not found"}), 404
        
    # 🛡️ THE SHIELD: Prevent deletion if ANY product is using it
    product_using_cat = Product.query.filter_by(category_id=cat_id).first()
    if product_using_cat:
        return jsonify({"error": "Cannot delete. There are products currently assigned to this category."}), 400

    try:
        cat.is_active = False # 👈 Soft Delete
        db.session.commit()
        return jsonify({"message": "Category moved to Recycle Bin"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    

@core.route('/sub-categories', methods=['GET'])
@jwt_required
def get_sub_categories():
    subs = SubCategory.query.order_by(SubCategory.display_order.asc(), SubCategory.name.asc()).all()
    # We include display_order so the frontend knows how to sort them globally
    return jsonify([{"id": s.id, "name": s.name, "display_order": s.display_order} for s in subs]), 200
@core.route('/sub-categories', methods=['POST'])
@jwt_required
def add_sub_category():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Sub-Category name is required"}), 400
        
    new_sub = SubCategory(
        name=data['name'], 
        display_order=data.get('display_order', 0),
        is_active=True  # 👈 Added this to support your new Recycle Bin logic
        # 💥 Removed match_rule
    )
    db.session.add(new_sub)
    db.session.commit()
    return jsonify({"message": "Sub-Category added successfully", "id": new_sub.id}), 201

@core.route('/sub-categories/<int:sub_id>', methods=['DELETE'])
@jwt_required
def delete_sub_category(sub_id):
    sub = SubCategory.query.get(sub_id)
    if not sub:
        return jsonify({"error": "Sub-Category not found"}), 404
        
    # 🛡️ THE SHIELD: Prevent deletion if ANY product is using it
    product_using_sub = Product.query.filter_by(sub_category_id=sub_id).first()
    if product_using_sub:
        return jsonify({"error": "Cannot delete. There are products currently assigned to this sub-category."}), 400

    try:
        sub.is_active = False # 👈 Soft Delete
        db.session.commit()
        return jsonify({"message": "Sub-Category moved to Recycle Bin"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Database error: {str(e)}"}), 500
# @core.route('/products', methods=['POST'])
# @jwt_required
# def add_product():
#     data = request.get_json()
#     sku = data.get('sku', '').upper()
    
#     # 🧠 AUTO-FILL CATEGORY IF BLANK
#     cat_id = data.get('category_id')
#     if not cat_id:
#         target = "OTHER"
#         if sku.startswith('BK'): target = "BLACK"
#         elif sku.startswith('GR'): target = "GREY"
#         elif sku.startswith('A'): target = "WHITE"
        
#         found = Category.query.filter_by(name=target).first()
#         if found: cat_id = found.id

#     # 🧠 AUTO-CREATE SUB-CATEGORY IF NEW
#     sub_cat_id = data.get('sub_category_id')
#     sub_name = data.get('sub_category_name', '').strip().upper()
#     if not sub_cat_id and sub_name:
#         sub = SubCategory.query.filter_by(name=sub_name).first()
#         if not sub:
#             sub = SubCategory(name=sub_name)
#             db.session.add(sub)
#             db.session.flush() # Gets the ID without committing yet
#         sub_cat_id = sub.id

#     new_p = Product(
#         name=data['name'],
#         product_code=sku,
#         category_id=cat_id,
#         sub_category_id=sub_cat_id,
#         department_id=get_active_department(),
#         current_stock=0,
#         is_active=True
#     )
#     db.session.add(new_p)
#     db.session.commit()
#     return jsonify({"message": "Product created", "id": new_p.id}), 201

# @core.route('/products', methods=['POST'])
# @jwt_required
# def add_product():
#     data = request.get_json()
#     active_dept = get_active_department()

#     if not active_dept:
#         return jsonify({"error": "Department context missing"}), 400
        
#     # 🛡️ THE GATEKEEPER: Stop empty products dead in their tracks
#     product_name = data.get('name', '').strip()
#     if not product_name:
#         return jsonify({"error": "Product Name is required and cannot be empty."}), 400
        
#     sku = data.get('product_code', data.get('sku', '')).strip()
#     if not sku:
#         return jsonify({"error": "Product SKU is required."}), 400

#     active_dept = get_active_department()

#     if not active_dept:
#         return jsonify({"error": "Department context missing"}), 400
    
    
#     # 1. Handle Category (Get existing or create new)
#     cat_name = data.get('category_name', 'OTHER').strip().upper()
#     category = Category.query.filter_by(name=cat_name).first()
#     if not category:
#         category = Category(name=cat_name)
#         db.session.add(category)
#         db.session.flush() # Get ID before product creation

#     # 2. Handle Sub-Category (Get existing or create new)
#     sub_name = data.get('sub_category_name', 'GENERAL').strip().upper()
#     sub_category = SubCategory.query.filter_by(name=sub_name).first()
#     if not sub_category:
#         sub_category = SubCategory(name=sub_name)
#         db.session.add(sub_category)
#         db.session.flush()

#     # 3. Create Product
#     new_product = Product(
#         name=data['name'],
#         # ✅ FIX: Use .get() to check for 'product_code' first, then fallback to 'sku'
#         product_code=data.get('product_code', data.get('sku', '')), 
#         category_id=category.id,
#         sub_category_id=sub_category.id,
#         department_id=active_dept,
#         current_stock=data.get('qty', 0),
#         min_stock=data.get('min_stock', 10),
#         max_stock=data.get('max_stock', 100),
#         unit=data.get('unit', 'pcs')
#     )
    
#     db.session.add(new_product)
#     db.session.commit()
    
#     # Clean up any previously orphaned categories (typos from previous edits)
    
#     return jsonify({"message": "Product added successfully"}), 201


@core.route('/products', methods=['POST'])
@jwt_required
def add_product():
    data = request.get_json()
    active_dept = get_active_department()

    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400
        
    # 🛡️ VALIDATE NAMES
    product_name = data.get('name')
    if not product_name or not str(product_name).strip():
        return jsonify({"error": "Product Name is required and cannot be empty."}), 400
    product_name = str(product_name).strip()
        
    sku = data.get('product_code', data.get('sku'))
    if not sku or not str(sku).strip():
        return jsonify({"error": "Product SKU is required."}), 400
    sku = str(sku).strip()

    # 🛑 VALIDATE NUMBERS (No Negatives!)
    try:
        qty = float(data.get('qty', 0))
        min_stock = float(data.get('min_stock', 10))
        max_stock = float(data.get('max_stock', 100))
        
        if qty < 0 or min_stock < 0 or max_stock < 0:
            return jsonify({"error": "Quantities and stock limits cannot be negative."}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid numeric values provided."}), 400

    try:
        

        cat_name = data.get('category_name', 'OTHER').strip().upper()
        category = Category.query.filter_by(name=cat_name).first()
        if not category:
            category = Category(name=cat_name)

        sub_name = data.get('sub_category_name', 'GENERAL').strip().upper()
        sub_category = SubCategory.query.filter_by(name=sub_name).first()
        if not sub_category:
            sub_category = SubCategory(name=sub_name)

        new_product = Product(
            name=product_name,
            product_code=sku,
            category_rel=category,       
            sub_category_rel=sub_category, 
            department_id=active_dept,
            current_stock=qty,
            min_stock=min_stock,
            max_stock=max_stock,
            unit=data.get('unit', 'pcs')
        )
        
        db.session.add(new_product)
        db.session.commit() 
        
        return jsonify({"message": "Product added successfully", "id": new_product.id}), 201

    except Exception as e:
        db.session.rollback() 
        return jsonify({"error": "Server error while adding product", "details": str(e)}), 500
    
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
        return jsonify({"error": "Supplier does not exist"}), 404
    
    if active_dept and supplier.department_id != active_dept: 
        return jsonify({"error": "User is not Authorized to make this action"}), 401

    if supplier.is_active == False: 
        return jsonify({"error": "Supplier is already inactive"}), 400
    
    supplier.is_active = False

    # 👇 CASCADE SOFT-DELETE: Remove associated transactions & reverse stock
    txns = Transaction.query.filter_by(supplier_id=id, is_active=True).all()
    for txn in txns:
        txn.is_active = False
        if txn.product:
            if txn.type == 'in':
                if txn.product.current_stock >= txn.quantity:
                    txn.product.current_stock -= txn.quantity
                else:
                    txn.product.current_stock = 0
                    txn.product.is_active = False # Auto-trash product if stock corruption occurs
            elif txn.type == 'return':
                txn.product.current_stock += txn.quantity
        
        log = ActivityLog(
            user_id=g.current_user.id if hasattr(g, 'current_user') else None, 
            action=f"Auto-deleted Txn #{txn.id} (Supplier removed)", 
            transaction_id=txn.id
        )
        db.session.add(log)

    try: 
        db.session.commit()
        return jsonify({"message": "Supplier and associated transactions successfully removed"}), 200
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
    
    if contractor.is_active == False: 
        return jsonify({"error": "Contractor is already inactive"}), 400
    
    contractor.is_active = False

    # 👇 CASCADE SOFT-DELETE: Remove associated transactions & reverse stock
    txns = Transaction.query.filter_by(contractor_id=id, is_active=True).all()
    for txn in txns:
        txn.is_active = False
        if txn.product:
            if txn.type == 'out':
                txn.product.current_stock += txn.quantity
            elif txn.type == 'return':
                if txn.product.current_stock >= txn.quantity:
                    txn.product.current_stock -= txn.quantity
                else:
                    txn.product.current_stock = 0
        
        log = ActivityLog(
            user_id=g.current_user.id if hasattr(g, 'current_user') else None, 
            action=f"Auto-deleted Txn #{txn.id} (Contractor removed)", 
            transaction_id=txn.id
        )
        db.session.add(log)

    try: 
        db.session.commit()
        return jsonify({"message": "Contractor and associated transactions successfully removed"}), 200
    except Exception as e: 
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/contractors/<int:id>/stock', methods=['GET'])
@jwt_required
def get_contractor_stock(id):
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = db.session.query(
        Product.id,
        Product.name,
        Product.product_code,
        Product.unit,
        func.sum(case(
            (Transaction.type == 'out', Transaction.quantity), 
            (Transaction.type == 'return', -Transaction.quantity),
            else_=0
        )).label('net_qty')
    ).join(Transaction)\
     .filter(
         Transaction.contractor_id == id, 
         Transaction.is_active == True
     )

    # ✅ Apply date filters if provided
    if start_date and end_date:
        query = query.filter(
            func.date(Transaction.date) >= start_date, 
            func.date(Transaction.date) <= end_date
        )

    results = query.group_by(Product.id, Product.name, Product.product_code, Product.unit)\
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
            transactions = Transaction.query.options(
                joinedload(Transaction.product),
                joinedload(Transaction.supplier),
                joinedload(Transaction.contractor)
            ).filter(
                Transaction.supplier_id == id,
                Transaction.product_id == product_id,
                func.lower(Transaction.type).in_(['in', 'return'])
            ).order_by(Transaction.created_at.desc()).all()

            return jsonify([t.to_dict() for t in transactions]), 200

        # --- MODE 2: Consolidated View (Main Table) ---
        results = db.session.query(
            Product.id,
            Product.name,
            Product.product_code,
            Product.current_stock, # 👈 1. ADD THIS TO SELECT
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
         .group_by(Product.id, Product.name, Product.product_code, Product.current_stock)\
         .all() # 👈 2. ADD TO GROUP BY

        data = []
        for r in results:
            data.append({
                "id": r.id,
                "name": r.name,
                "sku": r.product_code,
                "current_stock": float(r.current_stock or 0), # 👈 3. ADD TO RESPONSE
                "total_supplied": float(r.total_supplied or 0), 
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
    # per_page = min(per_page, 1000000)  

    # 2. Get Date Filters from Query Params
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    # 3. Build Base Query (Identical to get_transactions, but filtered by ID)
    query = Transaction.query.options(
        joinedload(Transaction.product),
        joinedload(Transaction.supplier),
        joinedload(Transaction.contractor)
    ).join(Product)\
     .outerjoin(Supplier)\
     .outerjoin(Contractor)\
     .filter(
         Transaction.product_id == id, # 👈 Specific Product Filter
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
    

@core.route('/stock/recalibrate', methods=['POST'])
@jwt_required
def recalibrate_stock():
    active_dept = get_active_department()
    
    # Base query for active products
    query = Product.query.filter_by(is_active=True)
    if active_dept:
        query = query.filter_by(department_id=active_dept)
        
    products = query.all()
    mismatch_count = 0
    
    for product in products:
        # 1. Sum all additions: "in" OR "return" from a contractor (supplier_id is None)
        additions = db.session.query(func.coalesce(func.sum(Transaction.quantity), 0)).filter(
            Transaction.product_id == product.id,
            Transaction.is_active == True,
            or_(
                Transaction.type == 'in',
                and_(Transaction.type == 'return', Transaction.supplier_id == None)
            )
        ).scalar()

        # 2. Sum all deductions: "out" OR "return" to a supplier (supplier_id is NOT None)
        deductions = db.session.query(func.coalesce(func.sum(Transaction.quantity), 0)).filter(
            Transaction.product_id == product.id,
            Transaction.is_active == True,
            or_(
                Transaction.type == 'out',
                and_(Transaction.type == 'return', Transaction.supplier_id != None)
            )
        ).scalar()

        # 3. Compare and update
        expected_stock = additions - deductions
        
        if product.current_stock != expected_stock:
            product.current_stock = expected_stock
            mismatch_count += 1
            
            # Optional: Log the recalibration activity
            log = ActivityLog(
                user_id=g.current_user.id,
                # 👇 Shortened the text to stay safely under 50 characters
                action=f"Fixed Prod #{product.id} stock to {expected_stock}" 
            )
            db.session.add(log)
            
    try:
        db.session.commit()
        return jsonify({"message": f"System recalibrated. {mismatch_count} product(s) fixed."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500    