from flask import Blueprint, jsonify, request, g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.extensions import db
from sqlalchemy import func, case, desc
from datetime import datetime, date
import calendar
from sqlalchemy.orm import joinedload
from sqlalchemy import or_, and_
import os
# Import ALL models
from app.models.order import Order, OrderItem
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
from app.models.supplierproduct import SupplierProduct, Notification

core = Blueprint('core', __name__, url_prefix='/core')

def get_effective_unit(product):
    """
    Strictly checks the Department's unit. 
    Uses Flask's 'g' object to cache the query and prevent N+1 database crashes!
    """
    if not product.department_id:
        return 'pcs'
        
    if not hasattr(g, 'dept_unit_cache'):
        g.dept_unit_cache = {}
        
    if product.department_id not in g.dept_unit_cache:
        dept = Department.query.get(product.department_id)
        g.dept_unit_cache[product.department_id] = str(dept.unit).strip().lower() if dept and dept.unit else 'pcs'
        
    return g.dept_unit_cache[product.department_id]

def calculate_new_stock(current_stock, amount, unit, is_adding=True):
    if not is_adding:
        amount = -amount
        
    safe_unit = str(unit).strip().lower() if unit else 'pcs'
    
    if safe_unit in ['gross', 'dozens', 'dozen', 'base12', 'brasspart']:
        def to_dozens(val):
            sign = -1 if val < 0 else 1
            val = abs(val)
            gross = int(val)
            
            # The User's Exact Rule: Multiply the exact decimal by 10
            dozens = round((val - gross) * 10, 4)
            
            # Handle the "Overflow Paradox" strings (.10 and .11)
            val_str = f"{val:.5f}".rstrip('0').rstrip('.')
            if '.' in val_str:
                dec_str = val_str.split('.')[1]
                if dec_str.startswith('10') or dec_str.startswith('11'):
                    # Force it to read 10.x or 11.x instead of 1.0x
                    dozens = float(dec_str[:2] + '.' + dec_str[2:]) if len(dec_str) > 2 else int(dec_str[:2])
            
            return sign * (gross * 12 + dozens)
            
        total_dozens = to_dozens(current_stock) + to_dozens(amount)
        
        sign = -1 if total_dozens < 0 else 1
        total_dozens = abs(total_dozens)
        
        new_gross = int(total_dozens // 12)
        new_dozens = round(total_dozens % 12, 4)
        
        # Save back to database format safely
        if new_dozens >= 10:
            # Save 10.5 dozen as .105 to prevent overflow
            decimal_string = str(new_dozens).replace('.', '')
            return sign * float(f"{new_gross}.{decimal_string}")
        else:
            # Normal Rule: Save 9.2 dozen as .92
            return sign * (new_gross + (new_dozens / 10.0))
            
    return round(current_stock + amount, 2)



# 👇 MUST BE FULLY LEFT-ALIGNED
def get_active_department():
    # Admins can "impersonate" departments via headers
    if g.role == "ADMIN":
        try:
            dept_id = request.headers.get("X-Department-Id")
            return int(dept_id) if dept_id else None
        except ValueError:
            return None
            
    # Workers always use their latest database-assigned department
    return g.current_user.department_id



@core.route('/clients', methods=['GET'])
@jwt_required
def get_clients():
    """Fetches all clients restricted to the active department"""
    active_dept = get_active_department()
    
    query = User.query.filter_by(role='CLIENT', is_active=True)
    
    if active_dept:
        query = query.filter_by(department_id=active_dept)
        
    clients = query.order_by(User.first_name.asc()).all()
    
    return jsonify([client.to_dict() for client in clients]), 200




@core.route('/stock/operate', methods=['POST'])
@jwt_required
def stock_operation():
    data = request.get_json()
    product_id = data.get('product_id')
    sku = data.get('sku')
    product_name = data.get('productName')
    op_type = data.get('type')
    notes = data.get('notes', '').strip()
    challan_id = data.get('challan_id', '').strip() if data.get('challan_id') else None

    try:
        qty = float(data.get('qty', 0))
        if qty <= 0: raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid positive quantity required"}), 400

    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    product = None
    if product_id:
        product = Product.query.get(product_id)
    if not product and sku and product_name:
        product = Product.query.filter_by(product_code=sku, name=product_name, department_id=active_dept).first()
    if not product and sku:
        product = Product.query.filter_by(product_code=sku, department_id=active_dept).first()

    if not product:
        if op_type != 'in': return jsonify({"error": "Product not found"}), 404
        if not product_name: return jsonify({"error": "Product Name required for new products"}), 400

        product = Product(
            name=product_name, product_code=sku, unit=data.get('unit', 'pcs'),
            current_stock=0.0, department_id=active_dept, is_active=True
        )
        db.session.add(product)
        db.session.flush()

    if product.department_id != active_dept and g.role != 'ADMIN':
        return jsonify({"error": "Cross-department operation blocked"}), 403

    txn_dept_id = product.department_id
    supplier_id = data.get('supplier_id')
    contractor_id = data.get('contractor_id')

    eff_unit = get_effective_unit(product)

    # 👇 FIX: Changed all entity creations to bind to `txn_dept_id` instead of `active_dept`
    if op_type == 'in':
        sup_name = data.get('supplier_name', '').strip()
        if not sup_name and not supplier_id: return jsonify({"error": "Supplier Name required."}), 400
        product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=True)
        if not supplier_id:
            supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == txn_dept_id).first()
            if not supplier:
                supplier = Supplier(name=sup_name, is_active=True, department_id=txn_dept_id)
                db.session.add(supplier)
                db.session.flush()
            supplier_id = supplier.id
        
    elif op_type == 'out':
        cont_name = data.get('contractor_name', '').strip()
        if not cont_name and not contractor_id: return jsonify({"error": "Contractor Name required."}), 400
        product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=False)
        if not contractor_id:
            contractor = Contractor.query.filter(Contractor.name.ilike(cont_name), Contractor.department_id == txn_dept_id).first()
            if not contractor:
                contractor = Contractor(name=cont_name, is_active=True, department_id=txn_dept_id)
                db.session.add(contractor)
                db.session.flush()
            contractor_id = contractor.id

    elif op_type == 'return':
        sup_name = data.get('supplier_name', '').strip()
        cont_name = data.get('contractor_name', '').strip()
        if not sup_name and not cont_name and not supplier_id and not contractor_id:
             return jsonify({"error": "A Supplier or Contractor is required to process a return."}), 400
        
        if sup_name or supplier_id:
            product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=False)
            if not supplier_id:
                supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == txn_dept_id).first()
                if not supplier:
                    supplier = Supplier(name=sup_name, is_active=True, department_id=txn_dept_id)
                    db.session.add(supplier)
                    db.session.flush()
                supplier_id = supplier.id
        elif cont_name or contractor_id:
            product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=True)  
            if not contractor_id:
                contractor = Contractor.query.filter(Contractor.name.ilike(cont_name), Contractor.department_id == txn_dept_id).first()
                if not contractor:
                    contractor = Contractor(name=cont_name, is_active=True, department_id=txn_dept_id)
                    db.session.add(contractor)
                    db.session.flush()
                contractor_id = contractor.id

    txn = Transaction(
        product_id=product.id, type=op_type, quantity=qty,
        supplier_id=supplier_id or data.get('supplier_id'),
        contractor_id=contractor_id or data.get('contractor_id'),
        department_id=txn_dept_id, created_by=g.current_user.id, is_active=True,
        notes=notes if notes else None, challan_id=challan_id
    )

    try:
        db.session.add(txn)
        db.session.add(product) 
        db.session.commit()
        return jsonify({"message": "Stock updated", "new_qty": product.current_stock}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
   

@core.route('/stock/operate/bulk', methods=['POST'])
@jwt_required
def bulk_stock_operation():
    data = request.get_json()
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    items = data.get('items', [])
    if not items:
        return jsonify({"error": "No items provided."}), 400

    op_type = data.get('type')
    supplier_name = data.get('supplier_name', '').strip()
    contractor_name = data.get('contractor_name', '').strip()
    challan_id = data.get('challan_id', '').strip() if data.get('challan_id') else None
    date_str = data.get('date', '').strip()
    notes = data.get('notes', '').strip()

    op_date = datetime.utcnow()
    if date_str:
        try:
            parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
            op_date = datetime.combine(parsed_date.date(), datetime.utcnow().time())
        except ValueError: pass 

    # 👇 IN-MEMORY CACHE: Prevents N+1 database crashes
    supplier_cache = {}
    contractor_cache = {}

    try:
        for item in items:
            prod_id = item.get('product_id')
            qty = float(item.get('qty', 0))
            if qty <= 0: continue

            product = Product.query.get(prod_id)
            if not product or (product.department_id != active_dept and g.role != 'ADMIN'):
                raise Exception(f"Invalid or unauthorized product ID: {prod_id}")

            eff_unit = get_effective_unit(product)
            prod_dept = product.department_id
            
            item_sup_id = None
            item_con_id = None

            # 👇 CONTEXTUAL LOOKUP: Binds the entity strictly to the product's true department
            if op_type == 'in':
                if not supplier_name: raise Exception("Supplier Name is required for Stock In.")
                if prod_dept not in supplier_cache:
                    sup = Supplier.query.filter(Supplier.name.ilike(supplier_name), Supplier.department_id == prod_dept).first()
                    if not sup:
                        sup = Supplier(name=supplier_name, is_active=True, department_id=prod_dept)
                        db.session.add(sup)
                        db.session.flush()
                    supplier_cache[prod_dept] = sup.id
                
                item_sup_id = supplier_cache[prod_dept]
                product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=True)

            elif op_type == 'out':
                if not contractor_name: raise Exception("Contractor Name is required for Stock Out.")
                if prod_dept not in contractor_cache:
                    con = Contractor.query.filter(Contractor.name.ilike(contractor_name), Contractor.department_id == prod_dept).first()
                    if not con:
                        con = Contractor(name=contractor_name, is_active=True, department_id=prod_dept)
                        db.session.add(con)
                        db.session.flush()
                    contractor_cache[prod_dept] = con.id
                
                item_con_id = contractor_cache[prod_dept]
                product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=False)

            elif op_type == 'return':
                if not supplier_name and not contractor_name:
                    raise Exception("A Supplier or Contractor is required to process a return.")
                
                if supplier_name:
                    if prod_dept not in supplier_cache:
                        sup = Supplier.query.filter(Supplier.name.ilike(supplier_name), Supplier.department_id == prod_dept).first()
                        if not sup:
                            sup = Supplier(name=supplier_name, is_active=True, department_id=prod_dept)
                            db.session.add(sup)
                            db.session.flush()
                        supplier_cache[prod_dept] = sup.id
                    item_sup_id = supplier_cache[prod_dept]
                    product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=False)
                
                elif contractor_name:
                    if prod_dept not in contractor_cache:
                        con = Contractor.query.filter(Contractor.name.ilike(contractor_name), Contractor.department_id == prod_dept).first()
                        if not con:
                            con = Contractor(name=contractor_name, is_active=True, department_id=prod_dept)
                            db.session.add(con)
                            db.session.flush()
                        contractor_cache[prod_dept] = con.id
                    item_con_id = contractor_cache[prod_dept]
                    product.current_stock = calculate_new_stock(product.current_stock, qty, eff_unit, is_adding=True)

            txn = Transaction(
                product_id=product.id, type=op_type, quantity=qty,
                supplier_id=item_sup_id, contractor_id=item_con_id, department_id=prod_dept,
                created_by=g.current_user.id, is_active=True,
                notes=notes if notes else None, challan_id=challan_id,
                created_at=op_date 
            )
            db.session.add(txn)
            db.session.add(product)

        db.session.commit()
        return jsonify({"message": "Bulk stock operation successful"}), 200

    except Exception as e:
        db.session.rollback() 
        return jsonify({"error": str(e)}), 400
  
    
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


@core.route('/products', methods=['GET'])
@jwt_required
def get_products():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    search_term = request.args.get('search', '').strip()
    cat_ids = request.args.get('cats', '')
    sub_ids = request.args.get('subs', '')
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("limit", 50, type=int), 100)
    
    # 1. Grab sorting parameters from the frontend
    sort_by = request.args.get('sort_by', 'id')
    sort_order = request.args.get('sort_order', 'desc')

    base_query = db.session.query(Product).options(
        joinedload(Product.category_rel),
        joinedload(Product.sub_category_rel)
    ).filter(
        Product.department_id == active_dept,
        Product.is_active == True
    )

    if search_term:
        base_query = base_query.filter(or_(
            Product.name.ilike(f"%{search_term}%"),
            Product.product_code.ilike(f"%{search_term}%")
        ))
    if cat_ids:
        base_query = base_query.filter(
            Product.category_id.in_([int(x) for x in cat_ids.split(',')])
        )
    if sub_ids:
        base_query = base_query.filter(
            Product.sub_category_id.in_([int(x) for x in sub_ids.split(',')])
        )

    # 2. Apply Dynamic Sorting
    if sort_by == 'name':
        order_col = func.lower(Product.name)
    elif sort_by == 'qty':
        order_col = Product.current_stock
    else:
        order_col = Product.id

    if sort_order == 'asc':
        base_query = base_query.order_by(order_col.asc(), Product.id.asc())
    else:
        base_query = base_query.order_by(order_col.desc(), Product.id.desc())

    # Execute pagination
    pagination = base_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    product_ids = [p.id for p in products]
    product_map = {p.id: p for p in products}

    # NO DATE FILTER: Dynamically calculate stock using ONLY active transactions to prevent bloat
    if not start_str or not end_str:
        # Fetch all active transactions for these products to compute true stock
        live_transactions = Transaction.query.filter(
            Transaction.is_active == True,
            Transaction.department_id == active_dept,
            Transaction.product_id.in_(product_ids)
        ).all()

        live_tallies = {pid: {'t_in': 0.0, 't_out': 0.0} for pid in product_ids}
        for txn in live_transactions:
            pid = txn.product_id
            p = product_map[pid]
            if txn.type == 'in' or (txn.type == 'return' and not txn.supplier_id):
                live_tallies[pid]['t_in'] = calculate_new_stock(
                    live_tallies[pid]['t_in'], txn.quantity, p.unit, is_adding=True
                )
            elif txn.type == 'out' or (txn.type == 'return' and txn.supplier_id):
                live_tallies[pid]['t_out'] = calculate_new_stock(
                    live_tallies[pid]['t_out'], txn.quantity, p.unit, is_adding=True
                )

        data = []
        for p in products:
            p_dict = p.to_dict()
            eff_unit = get_effective_unit(p)
            # Override stale shelf stock with mathematically verified active transaction stock
            p_dict['qty'] = calculate_new_stock(live_tallies[p.id]['t_in'], live_tallies[p.id]['t_out'], eff_unit, is_adding=False)
            p_dict['total_stock_in'] = None
            p_dict['total_stock_out'] = None
            data.append(p_dict)

        return jsonify({
            "data": data,
            "pagination": {
                "page": page, "per_page": per_page,
                "total": pagination.total, "pages": pagination.pages
            }
        }), 200

    # DATE FILTER ACTIVE: Query transactions within the bounding dates
    try:
        start_date = datetime.strptime(start_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(
            hour=23, minute=59, second=59
        )
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    transactions = Transaction.query.filter(
        Transaction.is_active == True,
        Transaction.department_id == active_dept,
        Transaction.product_id.in_(product_ids),
        Transaction.created_at.between(start_date, end_date)
    ).all()

    tallies = {pid: {'t_in': 0.0, 't_out': 0.0, 'moved': False} 
               for pid in product_ids}

    for txn in transactions:
        pid = txn.product_id
        p = product_map[pid]
        tallies[pid]['moved'] = True

        if txn.type == 'in' or (txn.type == 'return' and not txn.supplier_id):
            tallies[pid]['t_in'] = calculate_new_stock(
                tallies[pid]['t_in'], txn.quantity, p.unit, is_adding=True
            )
        elif txn.type == 'out' or (txn.type == 'return' and txn.supplier_id):
            tallies[pid]['t_out'] = calculate_new_stock(
                tallies[pid]['t_out'], txn.quantity, p.unit, is_adding=True
            )

    data = []
    for p in products:
        if not tallies[p.id]['moved']:
            continue  # Exclude products with no activity in the date range
        p_dict = p.to_dict()
        p_dict['total_stock_in'] = tallies[p.id]['t_in']
        p_dict['total_stock_out'] = tallies[p.id]['t_out']
        data.append(p_dict)

    return jsonify({
        "data": data,
        "pagination": {
            "page": page, "per_page": per_page,
            "total": pagination.total, "pages": pagination.pages
        }
    }), 200

@core.route('/orders/<int:order_id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_admin_order(order_id):
    order = Order.query.get_or_404(order_id)
    order.is_active = False # 👈 Soft Delete (Sends to Recycle Bin)
    db.session.commit()
    return jsonify({"message": "Order moved to Recycle Bin"}), 200


from datetime import date, timedelta
from sqlalchemy import func

@core.route('/analysis/production', methods=['GET'])
@jwt_required
def production_analysis():
    active_dept = get_active_department()
    months = request.args.get('months', 1, type=int)

    # Calculate cutoff date based on the time filter (1M, 3M, 6M, 9M, 12M)
    cutoff_date = date.today() - timedelta(days=30 * months)

    # 1. Get all active products
    products = Product.query.filter_by(department_id=active_dept, is_active=True).all()

    # 2. Get SUM of all pending order items within the date range
    pending_items = db.session.query(
        OrderItem.product_id,
        func.sum(OrderItem.quantity).label('total_ordered')
    ).join(Order).filter(
        Order.status == 'PENDING',
        Order.is_active == True,
        Order.department_id == active_dept,
        Order.order_date >= cutoff_date
    ).group_by(OrderItem.product_id).all()

    ordered_map = {pid: total for pid, total in pending_items}

    results = []
    for p in products:
        order_qty = ordered_map.get(p.id, 0)
        
        # Only show items that actually have pending orders
        if order_qty > 0:
            # Formula: To Produce = Order Qty - Stock Available (Minimum 0)
            to_produce = max(0, order_qty - p.current_stock)
            
            results.append({
                "id": p.id,
                "code": p.product_code,
                "name": p.name,
                "order_qty": float(order_qty),
                "in_stock": float(p.current_stock),
                "to_produce": float(to_produce)
            })

    # Sort so the highest "To Produce" is at the top
    results.sort(key=lambda x: x['to_produce'], reverse=True)
    return jsonify(results), 200

from sqlalchemy import or_
from datetime import date, timedelta

@core.route('/contractors', methods=['GET'])
@jwt_required
def get_contractors():
    active_dept = get_active_department() 
    if g.role == "ADMIN" and not active_dept:
         contractors = Contractor.query.filter_by(is_active=True).all()
    else:
         contractors = Contractor.query.filter_by(is_active=True, department_id=active_dept).all()
    
    # 👇 THE OPTIMIZATION: Fixes the N+1 Slowness 
    cutoff_date = date.today() - timedelta(days=30)
    contractor_ids = [c.id for c in contractors]
    
    overdue_contractor_ids = set()
    if contractor_ids:
        # Ask the database ONCE for all overdue orders matching these contractors
        overdue_orders = db.session.query(Order.contractor_id).filter(
            Order.contractor_id.in_(contractor_ids), 
            Order.status == 'PENDING', 
            or_(Order.is_active == True, Order.is_active == None), 
            or_(
    Order.required_date < date.today(), 
    and_(Order.order_date < cutoff_date, Order.required_date == None)
)
        ).distinct().all()
        overdue_contractor_ids = {row[0] for row in overdue_orders}
    
    results = []
    for c in contractors:
        c_dict = c.to_dict()
        c_dict['has_overdue'] = c.id in overdue_contractor_ids
        results.append(c_dict)
        
    return jsonify(results), 200

@core.route('/contractors/<int:id>', methods=['PUT'])
@jwt_required
def update_contractor(id):
    contractor = Contractor.query.get(id)
    if not contractor: return jsonify({"error": "Contractor not found"}), 404

    data = request.get_json()
    if 'name' in data: contractor.name = str(data['name']).strip()
    if 'phone' in data: contractor.phone = data['phone'] 
    
    if 'department_id' in data and data['department_id']:
        new_dept = int(data['department_id'])
        # If shifted to a new department, permanently nuke pending orders
        if contractor.department_id != new_dept:
            Order.query.filter_by(contractor_id=contractor.id, status='PENDING').delete()
            
        contractor.department_id = new_dept

    try:
        db.session.commit()
        return jsonify({"message": "Contractor updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500   

@core.route('/contractors/<int:id>/orders', methods=['GET'])
@jwt_required
def get_contractor_orders(id):
    active_dept = get_active_department()
    query = Order.query.filter(
        Order.contractor_id == id, 
        or_(Order.is_active == True, Order.is_active == None)
    ) 
    if active_dept:
        query = query.filter(Order.department_id == active_dept)
        
    orders = query.order_by(Order.created_at.desc()).all()
    return jsonify([o.to_dict() for o in orders]), 200


@core.route('/orders/<int:order_id>', methods=['PUT'])
@jwt_required
@admin_only
def edit_admin_order(order_id):
    order = Order.query.get_or_404(order_id)
    data = request.get_json()

    try:
        # 1. Update basic info & Increment Counter
        order.challan_number = data.get('challan_number', order.challan_number)
        if data.get('order_date'):
            order.order_date = datetime.strptime(data['order_date'], '%Y-%m-%d').date()
        
        order.edit_counter += 1

        # 2. SAFELY REBUILD CART (Preserving dispatched_qty)
        if 'items' in data and len(data['items']) > 0:
            existing_items = {item.product_id: item for item in order.items}
            new_product_ids = [int(item['product_id']) for item in data['items']]

            # A. Remove items not in the new payload
            for item in order.items:
                if item.product_id not in new_product_ids:
                    # PREVENT DELETING ALREADY SHIPPED ITEMS
                    if getattr(item, 'dispatched_qty', 0) > 0:
                        return jsonify({"error": f"Cannot remove '{item.product.name}'. {item.dispatched_qty} units have already been dispatched."}), 400
                    db.session.delete(item)

            # B. Update existing or Add new
            for item_data in data['items']:
                pid = int(item_data['product_id'])
                new_qty = float(item_data['qty'])

                if pid in existing_items:
                    existing_item = existing_items[pid]
                    # PREVENT REDUCING QTY BELOW WHAT WAS ALREADY SHIPPED
                    if getattr(existing_item, 'dispatched_qty', 0) > new_qty:
                        return jsonify({"error": f"Cannot reduce '{existing_item.product.name}' below {existing_item.dispatched_qty} (amount already sent)."}), 400
                    existing_item.quantity = new_qty
                else:
                    db.session.add(OrderItem(
                        order_id=order.id,
                        product_id=pid,
                        quantity=new_qty
                    ))

        db.session.commit()
        return jsonify({"message": "Order updated successfully!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
@core.route('/products/search', methods=['GET'])
@jwt_required
def search_products():
    active_dept = get_active_department()
    search_term = request.args.get('search', '').strip()

    query = Product.query.filter_by(department_id=active_dept, is_active=True)

    if search_term:
        query = query.filter(or_(
            Product.name.ilike(f"%{search_term}%"),
            Product.product_code.ilike(f"%{search_term}%")
        ))

    # Fast, lightweight query. Limits to top 50 matches for the dropdown.
    products = query.order_by(Product.name.asc()).limit(50).all()
    
    return jsonify([{"id": p.id, "name": p.name, "sku": p.product_code} for p in products]), 200


@core.route('/products/<int:id>', methods=['PUT'])
@jwt_required
def update_product(id):
    product = Product.query.get_or_404(id)
    active_dept = get_active_department()
    if g.role != 'ADMIN' and product.department_id != active_dept:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    try:
        if 'name' in data: product.name = str(data['name']).strip()
        if 'sku' in data: product.product_code = str(data['sku']).strip()
        if 'min_stock' in data: product.min_stock = float(data['min_stock'])
        if 'max_stock' in data: product.max_stock = float(data['max_stock'])
        if 'pcs_per_box' in data: product.pcs_per_box = int(data['pcs_per_box'])

        # Update Category/Sub by name (namespaced by dept)
        for field, model in [('category_name', Category), ('sub_category_name', SubCategory)]:
            if field in data:
                name = data[field].strip().upper() or ('OTHER' if field == 'category_name' else 'GENERAL')
                obj = model.query.filter_by(name=name, department_id=active_dept).first()
                if not obj:
                    max_ord = db.session.query(func.max(model.display_order)).filter_by(department_id=active_dept).scalar() or 0
                    obj = model(name=name, display_order=max_ord + 1, department_id=active_dept)
                    db.session.add(obj)
                    db.session.flush()
                
                if field == 'category_name': product.category_id = obj.id
                else: product.sub_category_id = obj.id

        db.session.commit()
        return jsonify({"message": "Product updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Update failed", "details": str(e)}), 500


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
        
        # 👇 FORCE INJECTION just in case your User.to_dict() method missed them
        user_dict['trusted_device_names'] = getattr(user, 'trusted_device_names', "None registered")
        user_dict['pending_device_name'] = getattr(user, 'pending_device_name', "Unknown Device")
        
        if user.department_id:
            dept = Department.query.get(user.department_id)
            user_dict['department_name'] = dept.name if dept else "Unknown"
        
        if user.requested_department_id:
            req_dept = Department.query.get(user.requested_department_id)
            user_dict['requested_department_name'] = req_dept.name if req_dept else "Unknown"
        
        results.append(user_dict)
        
    return jsonify(results), 200


@core.route('/approve-user', methods=['POST'])
@jwt_required
@admin_only
def approve_user():
    data = request.get_json()
    target_user_id = data.get('id')
    is_approved = data.get('approved')

    # 👇 1. FIND BY ID ONLY. Phone numbers cause silent mismatches.
    target_user = User.query.get(target_user_id)
    
    if not target_user: 
        return jsonify({"error": "User not found"}), 404

    try:
        if is_approved:
            if target_user.approval_status == 'PENDING_SIGNUP':
                target_user.is_active = True
                target_user.approval_status = 'APPROVED'
                
                if target_user.role == 'CLIENT':
                    existing_contractor = Contractor.query.filter_by(phone=target_user.phoneno).first()
                    if not existing_contractor:
                        new_contractor = Contractor(
                            name=f"{target_user.first_name} {target_user.last_name}".strip(),
                            phone=target_user.phoneno,
                            department_id=target_user.department_id,
                            is_active=True
                        )
                        db.session.add(new_contractor)

                elif target_user.role == 'SUPPLIER':
                    existing_supplier = Supplier.query.filter_by(phone_number=target_user.phoneno).first()
                    if not existing_supplier:
                        new_supplier = Supplier(
                            name=f"{target_user.first_name} {target_user.last_name}".strip(),
                            phone_number=target_user.phoneno,
                            department_id=target_user.department_id,
                            is_active=True
                        )
                        db.session.add(new_supplier)
                        
                        welcome_alert = Notification(
                            user_id=target_user.id,
                            title="Account Activated",
                            message="Welcome to the VMI Portal!"
                        )
                        db.session.add(welcome_alert)
                
            elif target_user.approval_status == 'PENDING_DEPT_CHANGE':
                target_user.department_id = target_user.requested_department_id
                target_user.requested_department_id = None
                target_user.approval_status = 'APPROVED'
                target_user.is_active = True

            # 👇 CASE 3: BULLETPROOF NEW DEVICE APPROVAL
            elif target_user.approval_status == 'PENDING_NEW_DEVICE':
                new_dev = str(target_user.pending_device_id or "").strip()
                new_name = str(target_user.pending_device_name or "Unknown").strip()
                
                trusted_str = str(target_user.trusted_devices or "").strip()
                trusted_names_str = str(target_user.trusted_device_names or "").strip()
                
                if new_dev and new_dev not in trusted_str:
                    target_user.trusted_devices = f"{trusted_str},{new_dev}" if trusted_str else new_dev
                
                if new_name and new_name not in trusted_names_str:
                    target_user.trusted_device_names = f"{trusted_names_str}, {new_name}" if trusted_names_str else new_name
                
                target_user.pending_device_id = None
                target_user.pending_device_name = None
                target_user.approval_status = 'APPROVED'
                target_user.is_active = True 
                
                db.session.commit()
                return jsonify({"message": f"New device approved for {target_user.first_name}."}), 200

            db.session.commit()
            return jsonify({"message": "Action approved"}), 200
        
        else:
            # REJECTION LOGIC
            if target_user.approval_status == 'PENDING_SIGNUP':
                db.session.delete(target_user)
                db.session.commit()
                return jsonify({"message": "User registration rejected."}), 200
            
            elif target_user.approval_status == 'PENDING_DEPT_CHANGE':
                target_user.requested_department_id = None
                target_user.approval_status = 'APPROVED'
                target_user.is_active = True 
                db.session.commit()
                return jsonify({"message": "Department change rejected."}), 200

            elif target_user.approval_status == 'PENDING_NEW_DEVICE':
                target_user.pending_device_id = None
                target_user.pending_device_name = None
                target_user.approval_status = 'APPROVED' 
                target_user.is_active = True 
                db.session.commit()
                return jsonify({"message": "New device blocked. Original devices restored."}), 200
            
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
    search_term = request.args.get('search', '').strip()
    
    view_all = request.args.get('view_all', 'false').lower() == 'true'
    
    # 👇 1. Grab sorting parameters from the frontend
    sort_by = request.args.get('sort_by', 'product')
    sort_order = request.args.get('sort_order', 'asc')

    header_dept = request.headers.get('X-Department-Id')
    active_dept = int(header_dept) if header_dept and header_dept.isdigit() else get_active_department()

    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("limit", 50, type=int), 100)

    query = Product.query.filter_by(is_active=True)
    
    if not view_all:
        query = query.filter_by(department_id=active_dept)
        
    if search_term:
        query = query.filter(or_(
            Product.name.ilike(f"%{search_term}%"),
            Product.product_code.ilike(f"%{search_term}%")
        ))

    # 👇 2. Apply Dynamic Sorting (Product Name or SKU only)
    if sort_by == 'sku':
        order_col = Product.product_code
    else:
        from sqlalchemy import func
        order_col = func.lower(Product.name) # Use lower() for accurate alphabetical sorting

    if sort_order == 'desc':
        query = query.order_by(order_col.desc(), Product.id.desc())
    else:
        query = query.order_by(order_col.asc(), Product.id.asc())

    # 👇 3. Execute pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    if not products:
        return jsonify({"data": [], "pagination": {"page": page, "per_page": per_page, "total": 0, "pages": 0}}), 200

    product_ids = [p.id for p in products]
    product_map = {p.id: p for p in products}

    # 👇 4. Base Transaction Query
    txn_filters = [
        Transaction.is_active == True,
        Transaction.product_id.in_(product_ids)
    ]
    
    # 👇 5. ONLY filter transactions by department if view_all is FALSE
    if not view_all:
        txn_filters.append(Transaction.department_id == active_dept)

    txn_query = Transaction.query.filter(*txn_filters)

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            txn_query = txn_query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError:
            pass

    transactions = txn_query.all()

    tallies = {pid: {'t_in': 0.0, 't_out': 0.0, 'r_in': 0.0, 'r_out': 0.0} for pid in product_ids}

    for txn in transactions:
        pid = txn.product_id
        eff_unit = get_effective_unit(product_map[pid])

        if txn.type == 'in':
            tallies[pid]['t_in'] = calculate_new_stock(tallies[pid]['t_in'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'out':
            tallies[pid]['t_out'] = calculate_new_stock(tallies[pid]['t_out'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'return':
            if not txn.supplier_id:
                tallies[pid]['t_in'] = calculate_new_stock(tallies[pid]['t_in'], txn.quantity, eff_unit, is_adding=True)
                tallies[pid]['r_in'] = calculate_new_stock(tallies[pid]['r_in'], txn.quantity, eff_unit, is_adding=True)
            else:
                tallies[pid]['t_out'] = calculate_new_stock(tallies[pid]['t_out'], txn.quantity, eff_unit, is_adding=True)
                tallies[pid]['r_out'] = calculate_new_stock(tallies[pid]['r_out'], txn.quantity, eff_unit, is_adding=True)

    results = []
    for p in products:
        results.append({
            "product_id": p.id,
            "product": p.name,
            "sku": p.product_code,
            "department_id": p.department_id,  # 👈 Crucial so your frontend knows where this came from!
            "total_in": tallies[p.id]['t_in'],
            "total_out": tallies[p.id]['t_out'],
            "return_in": tallies[p.id]['r_in'],
            "return_out": tallies[p.id]['r_out']
        })

    return jsonify({
        "data": results,
        "pagination": { "page": page, "per_page": per_page, "total": pagination.total, "pages": pagination.pages }
    }), 200


from flask import Response

from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import joinedload



import csv
import io
from flask import Response


@core.route('/products/export/json', methods=['GET'])
@jwt_required
def export_products_json():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    search_term = request.args.get('search', '').strip()
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    cat_ids = request.args.get('cats', '') 
    sub_ids = request.args.get('subs', '')

    product_query = Product.query.options(
        joinedload(Product.category_rel),
        joinedload(Product.sub_category_rel)
    ).filter(Product.department_id == active_dept, Product.is_active == True)

    if search_term:
        product_query = product_query.filter(or_(Product.name.ilike(f"%{search_term}%"), Product.product_code.ilike(f"%{search_term}%")))
    if cat_ids:
        product_query = product_query.filter(Product.category_id.in_([int(x) for x in cat_ids.split(',')]))
    if sub_ids:
        product_query = product_query.filter(Product.sub_category_id.in_([int(x) for x in sub_ids.split(',')]))

    products = product_query.all()
    if not products: return jsonify([]), 200

    product_map = {p.id: p for p in products}
    product_ids = list(product_map.keys())

    txn_query = Transaction.query.filter(Transaction.is_active == True, Transaction.department_id == active_dept, Transaction.product_id.in_(product_ids))
    is_custom_range = False
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            txn_query = txn_query.filter(Transaction.created_at.between(start_date, end_date))
            is_custom_range = True
        except ValueError: pass

    transactions = txn_query.all()
    tallies = {pid: {'t_in': 0.0, 't_out': 0.0, 'has_activity': False} for pid in product_ids}

    for txn in transactions:
        pid = txn.product_id
        eff_unit = get_effective_unit(product_map[pid])
        tallies[pid]['has_activity'] = True

        if txn.type == 'in' or (txn.type == 'return' and not txn.supplier_id):
            tallies[pid]['t_in'] = calculate_new_stock(tallies[pid]['t_in'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'out' or (txn.type == 'return' and txn.supplier_id):
            tallies[pid]['t_out'] = calculate_new_stock(tallies[pid]['t_out'], txn.quantity, eff_unit, is_adding=True)

    cso_records = CategorySubOrder.query.all()
    cso_map = {(so.category_id, so.sub_category_id): so.display_order for so in cso_records}
    groups, cat_orders, sub_orders = {}, {}, {}

    for p in products:
        # if is_custom_range and not tallies[p.id]['has_activity']: continue
        cat_name = p.category_rel.name if p.category_rel else 'OTHER'
        sub_name = p.sub_category_rel.name if p.sub_category_rel else 'GENERAL'
        cat_orders[cat_name] = (p.category_rel.display_order or 0) if p.category_rel else 9999
        
        if cat_name not in sub_orders: sub_orders[cat_name] = {}
        
        # 🚨 THE FIX: Check contextual order first, fallback to base sub-category order, then 9999
        contextual_order = cso_map.get((p.category_id, p.sub_category_id))
        base_sub_order = p.sub_category_rel.display_order if p.sub_category_rel else 9999
        
        sub_orders[cat_name][sub_name] = contextual_order if contextual_order is not None else base_sub_order
        
        if cat_name not in groups: groups[cat_name] = {}
        if sub_name not in groups[cat_name]: groups[cat_name][sub_name] = []

        eff_unit = get_effective_unit(p)
        current_stock = calculate_new_stock(tallies[p.id]['t_in'], tallies[p.id]['t_out'], eff_unit, False) if is_custom_range else p.current_stock

        eff_unit = get_effective_unit(p)
        # Calculate the net movement for the selected dates
        period_net = calculate_new_stock(tallies[p.id]['t_in'], tallies[p.id]['t_out'], eff_unit, False) if is_custom_range else p.current_stock

        groups[cat_name][sub_name].append({
            "code": p.product_code or '-', "name": p.name or '-',
            "in": tallies[p.id]['t_in'], 
            "out": tallies[p.id]['t_out'], 
            "period_stock": period_net,      
            "live_stock": p.current_stock,   
            "min_stock": p.min_stock, 
            "max_stock": p.max_stock  
        })
    export_data = []
    sorted_cats = sorted(groups.keys(), key=lambda c: (cat_orders.get(c, 9999), c))
    for cat_name in sorted_cats:
        export_data.append({"type": "category", "title": f"{cat_name} Category"})
        sorted_subs = sorted(groups[cat_name].keys(), key=lambda s: (sub_orders[cat_name].get(s, 9999), s))
        for sub_name in sorted_subs:
            export_data.append({"type": "subcategory", "title": sub_name})
            for item in sorted(groups[cat_name][sub_name], key=lambda x: str(x['code']).upper()):
                export_data.append({"type": "item", **item})

    return jsonify(export_data), 200



@core.route('/products/export/csv', methods=['GET'])
@jwt_required
def export_products_csv():
    active_dept = get_active_department()
    search_term = request.args.get('search', '').strip()
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    cat_ids = request.args.get('cats', '') 
    sub_ids = request.args.get('subs', '')

    product_query = Product.query.options(joinedload(Product.category_rel), joinedload(Product.sub_category_rel)).filter(Product.department_id == active_dept, Product.is_active == True)

    if search_term: product_query = product_query.filter(or_(Product.name.ilike(f"%{search_term}%"), Product.product_code.ilike(f"%{search_term}%")))
    if cat_ids: product_query = product_query.filter(Product.category_id.in_([int(x) for x in cat_ids.split(',')]))
    if sub_ids: product_query = product_query.filter(Product.sub_category_id.in_([int(x) for x in sub_ids.split(',')]))

    products = product_query.all()
    if not products: return Response("Category,Subcategory,Product Code,Product Name,In,Out,Stock\n", mimetype="text/csv")

    product_map = {p.id: p for p in products}
    product_ids = list(product_map.keys())

    txn_query = Transaction.query.filter(Transaction.is_active == True, Transaction.department_id == active_dept, Transaction.product_id.in_(product_ids))
    is_custom_range = False
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            txn_query = txn_query.filter(Transaction.created_at.between(start_date, end_date))
            is_custom_range = True
        except ValueError: pass

    transactions = txn_query.all()
    tallies = {pid: {'t_in': 0.0, 't_out': 0.0, 'has_activity': False} for pid in product_ids}

    for txn in transactions:
        pid = txn.product_id
        eff_unit = get_effective_unit(product_map[pid])
        tallies[pid]['has_activity'] = True

        if txn.type == 'in' or (txn.type == 'return' and not txn.supplier_id):
            tallies[pid]['t_in'] = calculate_new_stock(tallies[pid]['t_in'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'out' or (txn.type == 'return' and txn.supplier_id):
            tallies[pid]['t_out'] = calculate_new_stock(tallies[pid]['t_out'], txn.quantity, eff_unit, is_adding=True)

    cso_records = CategorySubOrder.query.all()
    cso_map = {(so.category_id, so.sub_category_id): so.display_order for so in cso_records}

    def get_sort_keys(p):
        cat_order = p.category_rel.display_order if p.category_rel else 9999
        cat_name = p.category_rel.name if p.category_rel else 'OTHER'
        sub_order = cso_map.get((p.category_id, p.sub_category_id), 9999) if p.sub_category_id else 9999
        sub_name = p.sub_category_rel.name if p.sub_category_rel else 'GENERAL'
        return (cat_order, cat_name, sub_order, sub_name, p.product_code or '')

    products.sort(key=get_sort_keys)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Category', 'Subcategory', 'Product Code', 'Product Name', 'In', 'Out', 'Period Net', 'Live Stock'])

    def get_sort_keys(p):
        cat_order = p.category_rel.display_order if p.category_rel else 9999
        cat_name = p.category_rel.name if p.category_rel else 'OTHER'
        
        # 🚨 THE FIX: Apply the same fallback logic here
        contextual_order = cso_map.get((p.category_id, p.sub_category_id))
        base_sub_order = p.sub_category_rel.display_order if p.sub_category_rel else 9999
        sub_order = contextual_order if contextual_order is not None else base_sub_order
        
        sub_name = p.sub_category_rel.name if p.sub_category_rel else 'GENERAL'
        return (cat_order, cat_name, sub_order, sub_name, p.product_code or '')
    
    
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=inventory_report.csv"})

import csv
import io
from flask import Response
from sqlalchemy import func, and_, or_


import csv
import io
from flask import Response
from xhtml2pdf import pisa
import io
from sqlalchemy import func, case, and_, or_
from sqlalchemy.orm import joinedload


@core.route('/transactions/export/csv', methods=['GET'])
@jwt_required
def export_transactions_csv():
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    search_term = request.args.get('search', '').strip()
    active_dept = get_active_department()

    txn_query = Transaction.query.filter(Transaction.is_active == True)
    if active_dept:
        txn_query = txn_query.filter(Transaction.department_id == active_dept)
        
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            txn_query = txn_query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError: pass

    transactions = txn_query.all()
    product_ids = list(set([t.product_id for t in transactions]))
    
    product_query = Product.query.filter(Product.is_active == True, Product.id.in_(product_ids))
    if search_term:
        product_query = product_query.filter(or_(Product.name.ilike(f"%{search_term}%"), Product.product_code.ilike(f"%{search_term}%")))
        
    products = product_query.all()
    product_map = {p.id: p for p in products}

    tallies = {p.id: {'tot_in': 0.0, 'ret_in': 0.0, 'tot_out': 0.0, 'ret_out': 0.0} for p in products}

    for txn in transactions:
        if txn.product_id not in product_map: continue
        pid = txn.product_id
        eff_unit = get_effective_unit(product_map[pid])

        if txn.type == 'in':
            tallies[pid]['tot_in'] = calculate_new_stock(tallies[pid]['tot_in'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'out':
            tallies[pid]['tot_out'] = calculate_new_stock(tallies[pid]['tot_out'], txn.quantity, eff_unit, is_adding=True)
        elif txn.type == 'return':
            if not txn.supplier_id: 
                tallies[pid]['tot_in'] = calculate_new_stock(tallies[pid]['tot_in'], txn.quantity, eff_unit, is_adding=True)
                tallies[pid]['ret_in'] = calculate_new_stock(tallies[pid]['ret_in'], txn.quantity, eff_unit, is_adding=True)
            else:
                tallies[pid]['tot_out'] = calculate_new_stock(tallies[pid]['tot_out'], txn.quantity, eff_unit, is_adding=True)
                tallies[pid]['ret_out'] = calculate_new_stock(tallies[pid]['ret_out'], txn.quantity, eff_unit, is_adding=True)

    sorted_products = sorted(products, key=lambda p: p.name.lower())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Product Name', 'SKU', 'Total In', 'Returns In', 'Total Out', 'Returns Out'])

    for p in sorted_products:
        writer.writerow([
            p.name, p.product_code or '-', 
            tallies[p.id]['tot_in'], tallies[p.id]['ret_in'], 
            tallies[p.id]['tot_out'], tallies[p.id]['ret_out']
        ])

    output.seek(0)
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=Transaction_History.csv"})
@core.route('/transactions/<int:id>', methods=['PUT'])
@jwt_required
@admin_only
def update_transaction(id):
    txn = Transaction.query.get(id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    if g.role != 'ADMIN' and txn.product.department_id != g.department_id:
         return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    product = txn.product
    eff_unit = get_effective_unit(product)

    try:
        # 1. Handle Quantity Update
        if 'qty' in data and data['qty'] != "":
            new_qty = float(data.get('qty'))
            if new_qty <= 0: raise ValueError("Quantity must be positive")
            
            old_qty = txn.quantity
            if old_qty != new_qty:
                # Reverse old stock, apply new stock
                if txn.type == 'in' or (txn.type == 'return' and not txn.supplier_id):
                    product.current_stock = calculate_new_stock(product.current_stock, old_qty, eff_unit, is_adding=False)
                    product.current_stock = calculate_new_stock(product.current_stock, new_qty, eff_unit, is_adding=True)
                elif txn.type == 'out' or (txn.type == 'return' and txn.supplier_id):
                    product.current_stock = calculate_new_stock(product.current_stock, old_qty, eff_unit, is_adding=True)
                    product.current_stock = calculate_new_stock(product.current_stock, new_qty, eff_unit, is_adding=False)
                
                txn.quantity = new_qty

                # 👇 2. NEW: THE ORDER SYNCHRONIZATION LINK
                if txn.order_id:
                    order = Order.query.get(txn.order_id)
                    if order:
                        order_item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
                        if order_item:
                            # Apply the exact difference to the dispatched total
                            qty_difference = new_qty - old_qty
                            order_item.dispatched_qty = max(0, (order_item.dispatched_qty or 0) + qty_difference)
                            
                            # Prevent dispatching more than ordered via edits
                            if order_item.dispatched_qty > order_item.quantity:
                                raise ValueError(f"Cannot dispatch more than the ordered quantity ({order_item.quantity})")
                            
                            db.session.add(order_item)

                        # Recalculate Master Order Status
                        total_ordered = sum(i.quantity for i in order.items)
                        total_dispatched = sum((i.dispatched_qty or 0) for i in order.items)

                        if total_dispatched >= total_ordered:
                            order.status = 'FULFILLED'
                        elif total_dispatched > 0:
                            order.status = 'PARTIAL'
                        else:
                            order.status = 'PENDING'

                        db.session.add(order)

        # 3. Handle Entity Name Update 
        if 'entity_name' in data and data['entity_name'].strip():
            entity_name = data['entity_name'].strip()
            
            if txn.type in ['in', 'return'] and txn.supplier_id:
                sup = Supplier.query.filter(Supplier.name.ilike(entity_name), Supplier.department_id == product.department_id).first()
                if not sup:
                    sup = Supplier(name=entity_name, is_active=True, department_id=product.department_id)
                    db.session.add(sup)
                    db.session.flush()
                txn.supplier_id = sup.id
                
            elif txn.type in ['out', 'return'] and txn.contractor_id:
                con = Contractor.query.filter(Contractor.name.ilike(entity_name), Contractor.department_id == product.department_id).first()
                if not con:
                    con = Contractor(name=entity_name, is_active=True, department_id=product.department_id)
                    db.session.add(con)
                    db.session.flush()
                txn.contractor_id = con.id

        # 4. Handle Challan & Notes
        if 'challan_id' in data:
            txn.challan_id = data['challan_id'].strip() if data['challan_id'].strip() else None
        if 'notes' in data:
            txn.notes = data['notes'].strip() if data['notes'].strip() else None

        log = ActivityLog(user_id=g.current_user.id, action=f"Edited Txn #{txn.id}", transaction_id=txn.id)
        db.session.add(log)
        db.session.add(product) 
        
        db.session.commit()
        return jsonify({"message": "Transaction updated and Order synchronized", "new_stock": product.current_stock}), 200

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
        if type == 'supplier':
            supplier = Supplier.query.get(id)
            if not supplier: return jsonify({"error": "Supplier not found"}), 404
            
            supplier.is_active = True
            db.session.add(supplier)
            
            txns = Transaction.query.filter_by(supplier_id=id, is_active=False).all()
            for txn in txns:
                if txn.product and txn.product.is_active:
                    eff_unit = get_effective_unit(txn.product)
                    if txn.type == 'in':
                        txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=True)
                    elif txn.type == 'return':
                        txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=False)
                
                txn.is_active = True
                db.session.add(txn)

            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Supplier & Transactions: {supplier.name}"[:50])
            db.session.add(log)

        elif type == 'contractor':
            contractor = Contractor.query.get(id)
            if not contractor: return jsonify({"error": "Contractor not found"}), 404
            
            contractor.is_active = True
            db.session.add(contractor)
            
            txns = Transaction.query.filter_by(contractor_id=id, is_active=False).all()
            for txn in txns:
                if txn.product and txn.product.is_active:
                    eff_unit = get_effective_unit(txn.product)
                    if txn.type == 'out':
                        txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=False)
                    elif txn.type == 'return':
                        txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=True)
                
                txn.is_active = True
                db.session.add(txn)

            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Contractor & Transactions: {contractor.name}"[:50])
            db.session.add(log)

        elif type == 'product':
            product = Product.query.get(id)
            if not product: return jsonify({"error": "Product not found"}), 404
            
            product.is_active = True
            db.session.add(product)
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Restored Product: {product.name}"[:50])
            db.session.add(log)

        elif type == 'transaction':
            txn = Transaction.query.get(id)
            if not txn: return jsonify({"error": "Transaction not found"}), 404
            product = txn.product

            if not product or not product.is_active:
                return jsonify({"error": "Cannot restore: Parent Product is deleted"}), 400

            eff_unit = get_effective_unit(product)

            # 👇 Roll forward to restore safely handling gross units
            if txn.type == 'in':
                product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=True)
            elif txn.type == 'out':
                product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=False)
            elif txn.type == 'return':
                if txn.supplier_id:
                    product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=False)
                else:
                    product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=True)

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

        db.session.commit()
        return jsonify({"message": f"{type.replace('_', '-').title()} restored successfully"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/transactions/<int:id>', methods=['DELETE'])
@jwt_required
def delete_transaction(id):
    txn = Transaction.query.get(id)
    if not txn: 
        return jsonify({"error": "Transaction not found"}), 404

    active_dept = get_active_department()
    if g.role != 'ADMIN' and txn.product.department_id != active_dept:
         return jsonify({"error": "Unauthorized to delete this transaction"}), 403

    product = txn.product
    eff_unit = get_effective_unit(product)

    # 1. Reverse the physical stock
    if txn.type == 'in':
        product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=False)
    elif txn.type == 'out':
        product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=True)
    elif txn.type == 'return':
        if txn.supplier_id:
            product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=True)
        else:
            product.current_stock = calculate_new_stock(product.current_stock, txn.quantity, eff_unit, is_adding=False)

    txn.is_active = False

    # 👇 2. NEW: THE ORDER SYNCHRONIZATION LINK
    if txn.order_id:
        order = Order.query.get(txn.order_id)
        if order:
            # Find the specific line item
            order_item = OrderItem.query.filter_by(order_id=order.id, product_id=product.id).first()
            if order_item:
                # Safely deduct the deleted dispatch quantity, flooring at 0
                order_item.dispatched_qty = max(0, (order_item.dispatched_qty or 0) - txn.quantity)
                db.session.add(order_item)

            # Recalculate the master order status based on remaining items
            total_ordered = sum(i.quantity for i in order.items)
            total_dispatched = sum((i.dispatched_qty or 0) for i in order.items)

            if total_dispatched >= total_ordered:
                order.status = 'FULFILLED'
            elif total_dispatched > 0:
                order.status = 'PARTIAL'
            else:
                order.status = 'PENDING'
            
            db.session.add(order)

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
            "message": "Transaction deleted and Order sync completed", 
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

        dept = Department.query.filter_by(id=w.department_id).first()
        results.append({
            "id": w.id,
            "name": f"{w.first_name} {w.last_name}",
            "phone": w.phoneno,
            "role": w.role,
            "department": dept.name if dept else "Unknown",
            "department_id": w.department_id,
            "is_active": w.is_active,
            "approval_status": w.approval_status,
            "requested_department_id": w.requested_department_id,
            "joined_at": w.created_at,
            # 👇 EXPLICITLY SENDING THE DEVICE NAMES TO THE FRONTEND
            "trusted_device_names": getattr(w, 'trusted_device_names', "None registered"),
            "pending_device_name": getattr(w, 'pending_device_name', "Unknown Device")
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
        db.session.flush() # 👇 Call flush so we get the new_user.id before committing

        # 👇 NEW: Auto-create Supplier profile if Admin chose the SUPPLIER role
        if new_user.role == 'SUPPLIER':
            existing_sup = Supplier.query.filter_by(phone_number=new_user.phoneno).first()
            if not existing_sup:
                new_sup = Supplier(
                    name=f"{new_user.first_name} {new_user.last_name}".strip(),
                    phone_number=new_user.phoneno,
                    department_id=new_user.department_id,
                    is_active=True
                )
                db.session.add(new_sup)
                
                # Send the Welcome Notification
                welcome_alert = Notification(
                    user_id=new_user.id,
                    title="Account Created",
                    message="Welcome to the VMI Portal! Your supplier account has been configured by an Admin."
                )
                db.session.add(welcome_alert)

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
    user = User.query.get(id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    data = request.get_json()

    # 🛡️ THE SUPER ADMIN SHIELD (By Phone Number)
    super_admin_phone = os.environ.get('SUPER_ADMIN_PHONE')
    if user.phoneno == super_admin_phone:
        if 'role' in data and data['role'] != 'ADMIN':
            return jsonify({"error": "You cannot demote the Super Admin account."}), 403
        if 'is_active' in data and data['is_active'] is False:
            return jsonify({"error": "You cannot disable the Super Admin account."}), 403

    # 🛡️ THE "DON'T LOCK YOURSELF OUT" SHIELD
    if g.current_user.id == id:
        if 'role' in data and data['role'] != g.current_user.role:
            return jsonify({"error": "You cannot change your own role."}), 400
        if 'is_active' in data and data['is_active'] is False:
            return jsonify({"error": "You cannot disable your own account."}), 400

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

    # 👇 NEW: 5. Auto-Create Profiles if Role was Changed
    try:
        if user.role == 'SUPPLIER':
            existing_sup = Supplier.query.filter_by(phone_number=user.phoneno).first()
            if not existing_sup:
                new_sup = Supplier(
                    name=f"{user.first_name} {user.last_name}".strip(),
                    phone_number=user.phoneno,
                    department_id=user.department_id,
                    is_active=True
                )
                db.session.add(new_sup)
                
                # Send the Welcome Notification
                welcome_alert = Notification(
                    user_id=user.id,
                    title="Account Configured",
                    message="Your account has been updated to a Supplier profile by an Admin. Welcome to the VMI Portal!"
                )
                db.session.add(welcome_alert)

        elif user.role == 'CLIENT':
            existing_contractor = Contractor.query.filter_by(phone=user.phoneno).first()
            if not existing_contractor:
                new_contractor = Contractor(
                    name=f"{user.first_name} {user.last_name}".strip(),
                    phone=user.phoneno,
                    department_id=user.department_id,
                    is_active=True
                )
                db.session.add(new_contractor)

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
        # 👈 Strict isolation applied here
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



@core.route('/contractors', methods=['POST'])
@jwt_required
def add_contractor():
    data = request.get_json()
    active_dept = get_active_department()

    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    # 1. Validate Name
    name = data.get('name')
    if not name or not str(name).strip():
        return jsonify({"error": "Contractor Name is required and cannot be empty."}), 400
    name = str(name).strip()

    # 2. Strictly Enforce 10-Digit Rule (Clean spaces/dashes safely)
    phone = data.get('phone')
    clean_phone = None
    if phone and str(phone).strip():
        # Keep ONLY digits
        clean_phone = ''.join(filter(str.isdigit, str(phone)))
        
        # If it's not exactly 10 digits, reject cleanly
        if len(clean_phone) != 10:
            return jsonify({"error": "Phone number must be exactly 10 digits."}), 400

    try:
        # 3. Check for Existing Contractor (Prevent duplicate crashes)
        existing = Contractor.query.filter(
            Contractor.name.ilike(name), 
            Contractor.department_id == active_dept
        ).first()
        
        if existing:
            if not existing.is_active:
                 return jsonify({"error": f"Contractor '{existing.name}' exists but is in the Recycle Bin. Please restore it from settings."}), 400
            return jsonify({"error": f"Contractor '{existing.name}' already exists in this department."}), 400

        # 4. Save New Contractor safely
        new_contractor = Contractor(
            name=name,
            phone=clean_phone, 
            department_id=active_dept,
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
    
    
@core.route('/contractor-transactions', methods=['GET'])
@jwt_required
def contractor_transaction_report():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    try:
        transactions = (
            db.session.query(Transaction)
            .filter(
                Transaction.department_id == active_dept,
                Transaction.type == 'out',
                Transaction.is_active == True,
                Transaction.contractor_id.isnot(None)
            )
            .order_by(Transaction.created_at.desc())
            .all()
        )

        if not transactions:
            return jsonify([]), 200

        result = []
        for txn in transactions:
            contractor = Contractor.query.get(txn.contractor_id)
            product = Product.query.get(txn.product_id)

            if not contractor or not product:
                continue  

            eff_unit = get_effective_unit(product)

            result.append({
                "contractor": contractor.name,
                "contractor_id": contractor.id,
                "product": product.name,
                "product_id": product.id,
                "sku": product.product_code,
                "unit": eff_unit,
                "date": txn.created_at.strftime("%Y-%m-%d"),
                "qty": to_display_unit(txn.quantity, eff_unit) 
            })

        return jsonify(result), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

from sqlalchemy import func


@core.route('/categories', methods=['GET'])
@jwt_required
def get_categories():
    active_dept = get_active_department()
    
    # 👇 THE TRUE RUTHLESS FIX: Block the request if context is missing
    if not active_dept:
        return jsonify({"error": "Department context missing. Cannot fetch categories."}), 400
    
    # 1. Fetch ONLY categories for this specific department
    cats = Category.query.filter_by(is_active=True, department_id=active_dept).order_by(Category.display_order.asc(), Category.id.asc()).all()
    
    # 2. Make sure we only scan products in this department
    active_pairs = db.session.query(Product.category_id, Product.sub_category_id)\
        .filter(Product.is_active == True, Product.department_id == active_dept)\
        .distinct().all()
        
    used_subs_by_cat = {}
    for cid, sid in active_pairs:
        if cid is None: continue 
        if cid not in used_subs_by_cat:
            used_subs_by_cat[cid] = set()
        if sid:
            used_subs_by_cat[cid].add(str(sid))

    result = []
    for c in cats:
        sub_orders_query = CategorySubOrder.query.filter_by(category_id=c.id).all()
        sub_orders_dict = {str(so.sub_category_id): so.display_order for so in sub_orders_query}
        
        dynamic_subs = used_subs_by_cat.get(c.id, set())
        for sid in dynamic_subs:
            if sid not in sub_orders_dict:
                sub_orders_dict[sid] = 999 
        
        result.append({
            "id": c.id, 
            "name": c.name, 
            "display_order": c.display_order,
            "sub_orders": sub_orders_dict 
        })
        
    return jsonify(result), 200


@core.route('/sub-categories', methods=['GET'])
@jwt_required
def get_sub_categories():
    active_dept = get_active_department()
    
    # 👇 THE TRUE RUTHLESS FIX: Block the request
    if not active_dept:
        return jsonify({"error": "Department context missing. Cannot fetch sub-categories."}), 400
    
    # Fetch ONLY sub-categories for this specific department
    subs = SubCategory.query.filter_by(is_active=True, department_id=active_dept)\
        .order_by(SubCategory.display_order.asc(), SubCategory.name.asc()).all()
        
    return jsonify([{"id": s.id, "name": s.name, "display_order": s.display_order} for s in subs]), 200

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
        
    # 1. Check if the frontend provided an explicit display_order
    # If not (or if it's 0), we calculate the true next order.
    provided_order = data.get('display_order', 0)
    
    if not provided_order or provided_order == 0:
        # Find the highest existing display_order in the database
        max_order = db.session.query(func.max(Category.display_order)).scalar()
        # If the table is empty, start at 1. Otherwise, take max + 1.
        next_order = (max_order or 0) + 1
    else:
        next_order = provided_order
        
    new_cat = Category(
        name=data['name'], 
        display_order=next_order,
        is_active=True 
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
    

@core.route('/sub-categories', methods=['POST'])
@jwt_required
def add_sub_category():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Sub-Category name is required"}), 400
        
    provided_order = data.get('display_order', 0)
    
    if not provided_order or provided_order == 0:
        # Find the highest existing display_order in the database
        max_order = db.session.query(func.max(SubCategory.display_order)).scalar()
        next_order = (max_order or 0) + 1
    else:
        next_order = provided_order
        
    new_sub = SubCategory(
        name=data['name'], 
        display_order=next_order,
        is_active=True 
    )
    db.session.add(new_sub)
    db.session.commit()
    return jsonify({"message": "Sub-Category added successfully", "id": new_sub.id}), 201

@core.route('/fix-order-zeros', methods=['GET'])
@jwt_required
@admin_only
def fix_order_zeros():
    # 1. Fix Categories
    cats = Category.query.order_by(Category.display_order.asc(), Category.id.asc()).all()
    for index, cat in enumerate(cats):
        cat.display_order = index + 1
        
    # 2. Fix Sub-Categories
    subs = SubCategory.query.order_by(SubCategory.display_order.asc(), SubCategory.id.asc()).all()
    for index, sub in enumerate(subs):
        sub.display_order = index + 1
        
    db.session.commit()
    return jsonify({"message": "All 0s have been replaced with sequential numbers!"}), 200

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

@core.route('/products', methods=['POST'])
@jwt_required
def add_product():
    data = request.get_json()
    active_dept = get_active_department()
    if not active_dept: return jsonify({"error": "Department context missing"}), 400
        
    product_name = str(data.get('name', '')).strip()
    sku = str(data.get('product_code', data.get('sku', ''))).strip()
    if not product_name or not sku:
        return jsonify({"error": "Name and SKU are required."}), 400

    try:
        # Category Helper
        cat_name = data.get('category_name', 'OTHER').strip().upper()
        category = Category.query.filter_by(name=cat_name, department_id=active_dept).first()
        if not category:
            max_order = db.session.query(func.max(Category.display_order)).filter_by(department_id=active_dept).scalar() or 0
            category = Category(name=cat_name, display_order=max_order + 1, department_id=active_dept)
            db.session.add(category)
            db.session.flush()

        # SubCategory Helper
        sub_name = data.get('sub_category_name', 'GENERAL').strip().upper()
        sub_category = SubCategory.query.filter_by(name=sub_name, department_id=active_dept).first()
        if not sub_category:
            max_sub_order = db.session.query(func.max(SubCategory.display_order)).filter_by(department_id=active_dept).scalar() or 0
            sub_category = SubCategory(name=sub_name, display_order=max_sub_order + 1, department_id=active_dept)
            db.session.add(sub_category)
            db.session.flush()

        new_product = Product(
            name=product_name, product_code=sku, category_rel=category,       
            sub_category_rel=sub_category, department_id=active_dept,
            current_stock=float(data.get('qty', 0)),
            min_stock=float(data.get('min_stock', 10)),
            max_stock=float(data.get('max_stock', 100)),
            unit=data.get('unit', 'pcs'), pcs_per_box=int(data.get('pcs_per_box', 100))
        )
        db.session.add(new_product)
        db.session.commit() 
        return jsonify({"message": "Product added", "id": new_product.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Add failed", "details": str(e)}), 500
    
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

    # 👇 CASCADE SOFT-DELETE: Remove associated transactions & reverse stock safely
    txns = Transaction.query.filter_by(supplier_id=id, is_active=True).all()
    for txn in txns:
        txn.is_active = False
        if txn.product:
            eff_unit = get_effective_unit(txn.product)
            if txn.type == 'in':
                new_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=False)
                if new_stock < 0:
                    txn.product.current_stock = 0
                    txn.product.is_active = False # Auto-trash product if stock corruption occurs
                else:
                    txn.product.current_stock = new_stock
            elif txn.type == 'return':
                txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=True)
        
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

    # 👇 CASCADE SOFT-DELETE: Remove associated transactions & reverse stock safely
    txns = Transaction.query.filter_by(contractor_id=id, is_active=True).all()
    for txn in txns:
        txn.is_active = False
        if txn.product:
            eff_unit = get_effective_unit(txn.product)
            if txn.type == 'out':
                txn.product.current_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=True)
            elif txn.type == 'return':
                new_stock = calculate_new_stock(txn.product.current_stock, txn.quantity, eff_unit, is_adding=False)
                if new_stock < 0:
                    txn.product.current_stock = 0
                else:
                    txn.product.current_stock = new_stock
        
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

    txn_query = Transaction.query.filter(
        Transaction.contractor_id == id,
        Transaction.is_active == True
    )

    # Optional date filter
    if start_date and end_date:
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d')
            ed = datetime.strptime(end_date, '%Y-%m-%d').replace(
                hour=23,
                minute=59,
                second=59
            )

            txn_query = txn_query.filter(
                Transaction.created_at.between(sd, ed)
            )

        except ValueError:
            pass

    print("NEW CONTRACTOR STOCK API RUNNING")

    # Fetch transactions + product relation
    transactions = txn_query.options(
        joinedload(Transaction.product)
    ).order_by(
        Transaction.created_at.desc()
    ).all()

    stock_list = []

    for txn in transactions:
        p = txn.product

        # Skip deleted/inactive products
        if not p or not p.is_active:
            continue

        stock_list.append({
            "transaction_id": txn.id,
            "product_id": p.id,
            "product_name": p.name,
            "sku": p.product_code,
            "unit": p.unit or 'pcs',
            "department_id": p.department_id,

            "challan_id": txn.challan_id,
            "notes": txn.notes or "",

            "date": txn.created_at.strftime('%Y-%m-%d'),
            "datetime": txn.created_at.isoformat(),

            "qty": txn.quantity,
            "type": txn.type
        })

    return jsonify(stock_list), 200



@core.route("/suppliers/<int:id>/products", methods=["GET"])
@jwt_required
def get_supplier_products(id): 
    try:
        product_id = request.args.get('product_id')

        # --- MODE 1: Drill Down ---
        if product_id:
            transactions = Transaction.query.options(
                joinedload(Transaction.product), joinedload(Transaction.supplier), joinedload(Transaction.contractor)
            ).join(Product).filter(
                Transaction.supplier_id == id, 
                Transaction.product_id == product_id,
                Transaction.is_active == True,         # 👈 FIX: Hide deleted transactions
                Product.is_active == True,             # 👈 FIX: Hide deleted products
                func.lower(Transaction.type).in_(['in', 'return'])
            ).order_by(Transaction.created_at.desc()).all()
            return jsonify([t.to_dict() for t in transactions]), 200

        # --- MODE 2: Consolidated View ---
        transactions = Transaction.query.options(joinedload(Transaction.product)).join(Product).filter(
            Transaction.supplier_id == id, 
            Transaction.is_active == True,             # 👈 FIX: Hide deleted transactions
            Product.is_active == True,                 # 👈 FIX: Hide deleted products
            func.lower(Transaction.type).in_(['in', 'return'])
        ).all()

        tallies = {}
        for txn in transactions:
            p = txn.product
            # 👈 FIX: Double safety check to ignore inactive products in memory
            if not p or not p.is_active: continue 
            
            eff_unit = get_effective_unit(p)
            if p.id not in tallies:
                tallies[p.id] = {
                    "id": p.id, "name": p.name, "sku": p.product_code, "total_supplied": 0.0, "last_supplied": txn.created_at
                }
                
            if txn.created_at > tallies[p.id]["last_supplied"]:
                tallies[p.id]["last_supplied"] = txn.created_at

            if txn.type == 'in':
                tallies[p.id]['total_supplied'] = calculate_new_stock(tallies[p.id]['total_supplied'], txn.quantity, eff_unit, True)
            elif txn.type == 'return':
                tallies[p.id]['total_supplied'] = calculate_new_stock(tallies[p.id]['total_supplied'], txn.quantity, eff_unit, False)

        data = []
        for pid, item in tallies.items():
            item["last_supplied"] = item["last_supplied"].strftime('%Y-%m-%d')
            data.append(item)

        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    
@core.route('/products/<int:id>/transactions', methods=['GET'])
@jwt_required
def get_product_transactions(id):
    product = Product.query.get(id)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    search_term = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'date').strip().lower()
    sort_order = request.args.get('sort_order', 'desc').strip().lower()

    query = Transaction.query.options(
        joinedload(Transaction.product),
        joinedload(Transaction.supplier),
        joinedload(Transaction.contractor)
    ).join(Product)\
     .outerjoin(Supplier)\
     .outerjoin(Contractor)\
     .filter(
         Transaction.product_id == id,
         Transaction.is_active == True,
         Product.is_active == True,
         or_(Supplier.id == None, Supplier.is_active == True),
         or_(Contractor.id == None, Contractor.is_active == True)
     )

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError:
            pass

    if search_term:
        query = query.filter(or_(
            Supplier.name.ilike(f"%{search_term}%"),
            Contractor.name.ilike(f"%{search_term}%"),
            Transaction.challan_id.ilike(f"%{search_term}%"),
            Transaction.notes.ilike(f"%{search_term}%"),
            db.cast(func.date(Transaction.created_at), db.String).ilike(f"%{search_term}%"),
            # 👇 Allows searching for "Manual Adjustment" dynamically
            and_(
                Transaction.supplier_id == None, 
                Transaction.contractor_id == None,
                db.literal("Manual Adjustment").ilike(f"%{search_term}%")
            )
        ))

    if sort_by == 'qty':
        order_col = Transaction.quantity
    elif sort_by == 'entity':
        # Smart sorting: Combines Supplier name, Contractor name, or defaults to Manual
        order_col = func.coalesce(Supplier.name, Contractor.name, "Manual Adjustment")
    else:
        order_col = Transaction.created_at

    if sort_order == 'asc':
        query = query.order_by(order_col.asc(), Transaction.id.asc())
    else:
        query = query.order_by(order_col.desc(), Transaction.id.desc())

    # 👇 Execute pagination
    paginated = query.paginate(page=page, per_page=per_page, error_out=False)

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
            "contractor_id": t.contractor_id,
            "notes": t.notes,
            "challan_id": t.challan_id
        })

    return jsonify({
        "data": results,
        "pagination": { "page": page, "per_page": per_page, "total": paginated.total, "pages": paginated.pages }
    }), 200   


@core.route('/stock/recalibrate', methods=['POST'])
@jwt_required
def recalibrate_stock():
    active_dept = get_active_department()
    
    prod_query = Product.query.filter_by(is_active=True)
    if active_dept:
        prod_query = prod_query.filter_by(department_id=active_dept)
        
    products = prod_query.all()
    if not products:
        return jsonify({"message": "No products found to recalibrate."}), 200

    # 1. Map out the products
    product_ids = [p.id for p in products]
    
    # 2. THE OPTIMIZATION: Fetch ALL transactions in a single, lightweight query
    txn_query = db.session.query(
        Transaction.product_id, Transaction.type, Transaction.quantity, Transaction.supplier_id
    ).filter(
        Transaction.is_active == True,
        Transaction.product_id.in_(product_ids)
    )
    
    if active_dept:
        txn_query = txn_query.filter(Transaction.department_id == active_dept)
        
    transactions = txn_query.all()

    # 3. Group transactions by product_id in Python's memory
    from collections import defaultdict
    txn_by_product = defaultdict(list)
    for pid, t_type, t_qty, sup_id in transactions:
        txn_by_product[pid].append((t_type, t_qty, sup_id))

    mismatch_count = 0
    
    # 4. Run the math from memory instantly
    for product in products:
        eff_unit = get_effective_unit(product)
        calculated_stock = 0.0
        
        for t_type, t_qty, sup_id in txn_by_product[product.id]:
            if t_type == 'in' or (t_type == 'return' and not sup_id):
                calculated_stock = calculate_new_stock(calculated_stock, t_qty, eff_unit, is_adding=True)
            elif t_type == 'out' or (t_type == 'return' and sup_id):
                calculated_stock = calculate_new_stock(calculated_stock, t_qty, eff_unit, is_adding=False)
        
        # Use abs() to handle tiny float variations
        if abs(product.current_stock - calculated_stock) > 0.001:
            product.current_stock = calculated_stock
            mismatch_count += 1
            
            log = ActivityLog(user_id=g.current_user.id, action=f"Fixed Prod #{product.id} stock to {calculated_stock}"[:50])
            db.session.add(log)
            
    try:
        db.session.commit()
        return jsonify({"message": f"System recalibrated. {mismatch_count} product(s) fixed."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
    

# ==========================================
# 🚀 VMI: VENDOR MANAGED INVENTORY SYSTEM
# ==========================================

@core.route('/suppliers/<int:supplier_id>/link-products', methods=['POST'])
@jwt_required
@admin_only
def link_supplier_products(supplier_id):
    """
    ADMIN: Manually assigns products to a specific supplier.
    Expected JSON: {"product_ids": [1, 5, 8]}
    """
    supplier = Supplier.query.get_or_404(supplier_id)
    data = request.get_json()
    product_ids = data.get('product_ids', [])

    try:
        SupplierProduct.query.filter_by(supplier_id=supplier.id).delete()
        for pid in product_ids:
            new_link = SupplierProduct(supplier_id=supplier.id, product_id=pid)
            db.session.add(new_link)
            
        db.session.commit()
        return jsonify({"message": f"Successfully updated assigned products for {supplier.name}"}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@core.route('/suppliers/<int:supplier_id>/linked-products', methods=['GET'])
@jwt_required
@admin_only
def get_supplier_linked_products(supplier_id):
    """ADMIN: Fetches the IDs of products currently assigned to a supplier"""
    links = SupplierProduct.query.filter_by(supplier_id=supplier_id).all()
    return jsonify([link.product_id for link in links]), 200


@core.route('/suppliers/my-vmi-dashboard', methods=['GET'])
@jwt_required
def get_my_vmi_dashboard():
    """
    SUPPLIER: Fetches explicitly assigned products with LAZY LOADING (Pagination)
    and calculates the traffic light status based on min/max stock.
    """
    if g.role != 'SUPPLIER': 
        return jsonify({"error": "Unauthorized"}), 403

    supplier = Supplier.query.filter_by(phone_number=g.current_user.phoneno).first()
    if not supplier:
        return jsonify({"error": "Supplier profile not found. Please contact Admin."}), 404

    # 1. Get assigned Product IDs
    assigned_links = SupplierProduct.query.filter_by(supplier_id=supplier.id).all()
    assigned_pids = [link.product_id for link in assigned_links]
    
    # 2. Extract Pagination Variables
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("limit", 20, type=int), 100) # Safe Lazy Load Limit
    search_term = request.args.get("search", "").strip()
    
    if not assigned_pids:
        return jsonify({"data": [], "pagination": {"page": page, "per_page": per_page, "total": 0, "pages": 0}}), 200

    # 3. Build the Query
    query = Product.query.filter(Product.id.in_(assigned_pids), Product.is_active == True)
    if search_term:
        query = query.filter(or_(
            Product.name.ilike(f"%{search_term}%"),
            Product.product_code.ilike(f"%{search_term}%")
        ))

    # 4. Execute Paginated Query
    pagination = query.order_by(Product.name.asc()).paginate(page=page, per_page=per_page, error_out=False)
    
    results = []
    for p in pagination.items:
        # 🚦 The Traffic Light Logic
        status = "🟢 GREEN"
        if p.current_stock <= p.min_stock:
            status = "🔴 RED"
        elif p.current_stock < p.max_stock:
            status = "🟡 YELLOW"

        results.append({
            "id": p.id,
            "name": p.name,
            "sku": p.product_code,
            "current_stock": p.current_stock,
            "min_stock": p.min_stock,
            "max_stock": p.max_stock,
            "status": status,
            "unit": p.unit
        })

    return jsonify({
        "data": results,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": pagination.total,
            "pages": pagination.pages
        }
    }), 200

@core.route('/system/trigger-vmi-alerts', methods=['POST'])
@jwt_required
@admin_only
def trigger_vmi_alerts():
    """
    ADMIN/SYSTEM: Scans all products assigned to suppliers. 
    If stock is below min_stock, generates an In-App Notification.
    """
    assigned_products = db.session.query(Product, SupplierProduct.supplier_id)\
        .join(SupplierProduct, SupplierProduct.product_id == Product.id)\
        .filter(Product.is_active == True).all()

    alerts_sent = 0

    for product, supplier_id in assigned_products:
        if product.current_stock <= product.min_stock:
            
            supplier = Supplier.query.get(supplier_id)
            user_account = User.query.filter_by(phoneno=supplier.phone_number).first()
            
            if user_account:
                # Prevent spam by checking if alerted today
                recent_alert = Notification.query.filter(
                    Notification.user_id == user_account.id,
                    Notification.message.like(f"%{product.product_code}%"),
                    Notification.created_at >= datetime.utcnow().date()
                ).first()

                if not recent_alert:
                    alert = Notification(
                        user_id=user_account.id,
                        title="CRITICAL: Low Stock Alert",
                        message=f"Product {product.name} (SKU: {product.product_code}) is running low ({product.current_stock} {product.unit} remaining). Please arrange production/dispatch immediately."
                    )
                    db.session.add(alert)
                    alerts_sent += 1

    db.session.commit()
    return jsonify({"message": f"Scan complete. {alerts_sent} alerts generated."}), 200


# ==========================================
# IN-APP NOTIFICATION ROUTES
# ==========================================
@core.route('/notifications', methods=['GET'])
@jwt_required
def get_my_notifications():
    """Fetches unread notifications for the logged-in supplier"""
    notifs = Notification.query.filter_by(user_id=g.current_user.id, is_read=False).order_by(desc(Notification.created_at)).limit(20).all()
    return jsonify([n.to_dict() for n in notifs]), 200

@core.route('/notifications/<int:notif_id>/read', methods=['PUT'])
@jwt_required
def mark_notification_read(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.user_id != g.current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
        
    notif.is_read = True
    db.session.commit()
    return jsonify({"message": "Marked as read"}), 200



from app.models.order import Order, OrderItem

@core.route('/orders/<int:order_id>/fulfill', methods=['POST'])
@jwt_required
@admin_only
def fulfill_contractor_order(order_id):
    data = request.get_json()
    order = Order.query.get_or_404(order_id)
    challan_id = data.get('challan_id', '').strip()
    
    if not challan_id:
        return jsonify({"error": "Challan ID is required for fulfillment"}), 400

    # Safely map the payload. Fallback to 0 if anything is weird.
    dispatch_data = {int(item['item_id']): float(item.get('dispatch_qty', 0)) for item in data.get('items', [])}

    try:
        total_pending_remaining = 0
        
        for item in order.items:
            dispatch_qty = dispatch_data.get(item.id, 0.0)
            
            # Safe fallback if the database has 'None' for older items
            current_dispatched = item.dispatched_qty or 0.0
            pending = item.quantity - current_dispatched
            
            # If no dispatch for this item, add its pending to the total and skip
            if dispatch_qty <= 0:
                total_pending_remaining += pending
                continue

            if dispatch_qty > pending:
                return jsonify({"error": f"Cannot dispatch {dispatch_qty}. Only {pending} pending for {item.product.name}."}), 400
            
            # 1. Deduct Stock
            product = item.product
            eff_unit = get_effective_unit(product)
            product.current_stock = calculate_new_stock(product.current_stock, dispatch_qty, eff_unit, is_adding=False)
            
            # 2. Update Order Item Status
            item.dispatched_qty = current_dispatched + dispatch_qty
            
            # 3. Create the official Transaction record (The Challan)
            # CRITICAL FIX: Ensure quantity is set to dispatch_qty, not pending!
            txn = Transaction(
                product_id=product.id,
                order_id=order.id,
                type='out',
                quantity=dispatch_qty, 
                contractor_id=order.contractor_id,
                department_id=order.department_id,
                created_by=g.current_user.id,
                is_active=True,
                challan_id=challan_id,
                notes=f"Partial dispatch from Order #{order.id}" if dispatch_qty < pending else f"Final dispatch from Order #{order.id}"
            )
            db.session.add(txn)
            db.session.add(product)
            
            # Add whatever is left over to the running total
            total_pending_remaining += (pending - dispatch_qty)

        # 4. Update Master Order Status
        if total_pending_remaining <= 0:
            order.status = 'FULFILLED'
        elif total_pending_remaining < sum(i.quantity for i in order.items):
            order.status = 'PARTIAL'

        db.session.commit()
        return jsonify({"message": "Dispatch successful and Challan generated!"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
@core.route('/admin/orders', methods=['GET'])
@jwt_required
@admin_only
def get_admin_orders():
    active_dept = get_active_department()
    query = Order.query.filter(or_(Order.is_active == True, Order.is_active == None))

    if active_dept:
        query = query.filter(Order.department_id == active_dept)

    orders = query.order_by(Order.created_at.desc()).all()
    results = []
    for order in orders:
        data = order.to_dict()
        data['department_id'] = order.department_id
        results.append(data)

    return jsonify(results), 200


@core.route('/admin/orders/place', methods=['POST'])
@jwt_required
@admin_only
def admin_place_order():
    """Admin manually places an order for a Contractor (Client)"""
    data = request.get_json()
    contractor_id = data.get('contractor_id')
    active_dept = data.get('department_id') or get_active_department()
    items = data.get('items', [])
    
    # 👇 NEW: Capture the Challan Number
    challan_number = data.get('challan_number', '').strip()

    if not contractor_id or not items:
        return jsonify({"error": "Contractor and items are required"}), 400

    try:
        new_order = Order(
            contractor_id=contractor_id,
            department_id=active_dept,
            challan_number=challan_number if challan_number else None, # 👈 Save it here
            notes=data.get('notes', ''),
            status='PENDING'
        )
        db.session.add(new_order)
        db.session.flush()

        for item in items:
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=item['product_id'],
                quantity=float(item['qty']) 
            )
            db.session.add(order_item)

        db.session.commit()
        return jsonify({"message": "Order placed successfully!", "order_id": new_order.id}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500   


#clients routes
# ==========================================
# 🚀 CLIENT PORTAL ROUTES
# ==========================================

@core.route('/client/products', methods=['GET'])
@jwt_required
def get_client_products():
    """CLIENT: Fetches active products with dynamic search and a strict limit to prevent timeouts."""
    if g.role != 'CLIENT': return jsonify({"error": "Unauthorized"}), 403
    
    search_term = request.args.get('search', '').strip()
    query = Product.query.filter_by(department_id=g.current_user.department_id, is_active=True)
    
    if search_term:
        query = query.filter(or_(
            Product.name.ilike(f"%{search_term}%"),
            Product.product_code.ilike(f"%{search_term}%")
        ))
        
    # Limit to 50 to prevent frontend freezing/timeouts!
    products = query.order_by(Product.name.asc()).limit(50).all()
    return jsonify([p.to_dict() for p in products]), 200

@core.route('/client/orders', methods=['POST'])
@jwt_required
def place_client_order():
    """CLIENT: Submits a new pending order from the cart."""
    if g.role != 'CLIENT':
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(force=True) or {}

    contractor = Contractor.query.filter_by(
        phone=g.current_user.phoneno
    ).first()

    if not contractor:
        return jsonify({"error": "Contractor profile not found"}), 404

    try:
        # ------------------------------------------------------------
        # Your frontend is sending:
        # {
        #   "items": {
        #       "items": [
        #           {"product_id": 1468, "qty": 800}
        #       ],
        #       "required_date": "2026-05-20"
        #   }
        # }
        #
        # So the actual payload is nested inside data["items"].
        # ------------------------------------------------------------

        # Extract the real payload
        payload = data.get('items', {})

        # Extract order items
        items = payload.get('items', [])

        # Extract required date
        required_date = None
        required_date_str = payload.get('required_date')

        if required_date_str:
            required_date = datetime.strptime(
                required_date_str,
                '%Y-%m-%d'
            ).date()

        # Validate items
        if not isinstance(items, list) or len(items) == 0:
            return jsonify({
                "error": "No items provided",
                "received": data
            }), 400

        # Create order header
        new_order = Order(
            contractor_id=contractor.id,
            department_id=contractor.department_id,
            status='PENDING',
            required_date=required_date
        )
        db.session.add(new_order)
        db.session.flush()

        # Create order items
        for item in items:
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=int(item['product_id']),
                quantity=float(item['qty'])  # Stored in PCS
            )
            db.session.add(order_item)

        db.session.commit()

        return jsonify({
            "message": "Order placed successfully!",
            "order_id": new_order.id
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "error": str(e)
        }), 500

@core.route('/client/orders', methods=['GET'])
@jwt_required
def get_client_orders():
    """CLIENT: Fetches their pending/active orders."""
    if g.role != 'CLIENT': return jsonify({"error": "Unauthorized"}), 403
    
    contractor = Contractor.query.filter_by(phone=g.current_user.phoneno).first()
    if not contractor: return jsonify([]), 200
    
    orders = Order.query.filter_by(
        contractor_id=contractor.id, 
        is_active=True
    ).order_by(Order.created_at.desc()).all()
    
    return jsonify([o.to_dict() for o in orders]), 200


@core.route('/client/dispatches', methods=['GET'])
@jwt_required
def get_client_dispatches():
    """CLIENT: Fetches official dispatches (Stock Out transactions attached to their profile)."""
    if g.role != 'CLIENT': return jsonify({"error": "Unauthorized"}), 403
    
    contractor = Contractor.query.filter_by(phone=g.current_user.phoneno).first()
    if not contractor: return jsonify([]), 200
    
    # Dispatches are essentially "Stock Out" transactions assigned to this contractor
    txns = Transaction.query.options(joinedload(Transaction.product)).filter_by(
        contractor_id=contractor.id, 
        type='out', 
        is_active=True
    ).order_by(Transaction.created_at.desc()).all()
    
    results = []
    for t in txns:
        t_dict = t.to_dict()
        t_dict['product_name'] = t.product.name if t.product else "Unknown"
        t_dict['sku'] = t.product.product_code if t.product else "Unknown"
        t_dict['pcs_per_box'] = t.product.pcs_per_box if t.product else 100
        results.append(t_dict)
        
    return jsonify(results), 200               