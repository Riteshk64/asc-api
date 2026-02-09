from flask import Blueprint, jsonify, request, g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.extensions import db
from sqlalchemy import func, case, desc
from datetime import datetime

# Import ALL models
from app.models.department import Department
from app.models.supplier import Supplier
from app.models.contractor import Contractor
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.user import User  
from app.models.activity_log import ActivityLog

core = Blueprint('core', __name__, url_prefix='/core')

# ==========================================
# HELPER: Context Switcher
# ==========================================
def get_active_department():
    """
    Decides which Department's data to show.
    - ADMIN: Uses 'X-Department-Id' header (Context Switch).
    - WORKER: Uses their fixed 'department_id' from token.
    """
    if g.role == "ADMIN":
        try:
            dept_id = request.headers.get("X-Department-Id")
            return int(dept_id) if dept_id else None
        except ValueError:
            return None
    return g.department_id


# ==========================================
# 1. STOCK OPERATIONS (In/Out/Quick Adjust)
# ==========================================
@core.route('/stock/operate', methods=['POST'])
@jwt_required
def stock_operation():
    data = request.get_json()
    sku = data.get('sku')
    op_type = data.get('type')  # 'in', 'out', 'return'
    
    try:
        qty = float(data.get('qty', 0))
        if qty <= 0: raise ValueError
    except ValueError:
        return jsonify({"error": "Invalid positive quantity required"}), 400

    if not sku or not op_type:
        return jsonify({"error": "SKU and operation type are required"}), 400

    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    # 1. Find product
    product = Product.query.filter_by(product_code=sku, department_id=active_dept).first()

    # 2. PRODUCT NOT FOUND LOGIC
    if not product:
        if op_type != 'in':
            return jsonify({"error": "Product not found"}), 404

        # For Stock IN, we allow creating new products
        product_name = data.get('productName')
        if not product_name:
            return jsonify({"error": "Product Name is required for new products"}), 400

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

    # 3. Security: Prevent Cross-Department Operations
    if product.department_id != active_dept:
        return jsonify({"error": "You cannot operate on another department's stock"}), 403

    supplier_id = None
    contractor_id = None
    default_name = "Manual Adjustment"

    # --- LOGIC: STOCK IN ---
    if op_type == 'in':
        product.current_stock += qty

        # Use provided name OR default to "Manual Adjustment" for quick buttons
        sup_name = data.get('supplier_name') or default_name
        sup_name = sup_name.strip()
        
        supplier = Supplier.query.filter(Supplier.name.ilike(sup_name), Supplier.department_id == active_dept).first()
        if not supplier:
            supplier = Supplier(name=sup_name, is_active=True, department_id=active_dept)
            db.session.add(supplier)
            db.session.flush()
        supplier_id = supplier.id

    # --- LOGIC: STOCK OUT ---
    elif op_type == 'out':
        if product.current_stock < qty:
            return jsonify({"error": f"Insufficient stock. Current: {product.current_stock}"}), 400

        product.current_stock -= qty

        # Use provided name OR default to "Manual Adjustment" for quick buttons
        cont_name = data.get('contractor_name') or default_name
        cont_name = cont_name.strip()
        
        contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
        if not contractor:
            contractor = Contractor(name=cont_name, is_active=True)
            db.session.add(contractor)
            db.session.flush()
        contractor_id = contractor.id

    # --- LOGIC: RETURN ---
    elif op_type == 'return':
        product.current_stock += qty
        
        cont_name = data.get('contractor_name') or default_name
        cont_name = cont_name.strip()
        
        contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
        if not contractor:
            contractor = Contractor(name=cont_name, is_active=True)
            db.session.add(contractor)
            db.session.flush()
        contractor_id = contractor.id
        
        # Save 'return' as 'in' in DB usually, or keep 'return' if your DB supports it.
        # Assuming we keep 'return' in DB for clarity, otherwise switch op_type='in' here.

    # Create Transaction
    txn = Transaction(
        product_id=product.id,
        type=op_type,
        quantity=qty,
        supplier_id=supplier_id,
        contractor_id=contractor_id,
        created_by=g.current_user.id,
        is_active=True 
    )

    try:
        db.session.add(txn)
        
        # Activity Log
        log = ActivityLog(
            user_id=g.current_user.id,
            action=f"Stock {op_type.upper()}: {qty} {product.unit} - {product.name}",
            transaction_id=txn.id
        )
        db.session.add(log)
        
        # Explicitly update product to ensure stock change saves
        db.session.add(product) 
        db.session.commit()

        return jsonify({
            "message": "Stock updated successfully",
            "new_qty": product.current_stock
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


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
@core.route('/products/<int:id>', methods=['PUT'])
@jwt_required
def update_product(id):
    product = Product.query.get(id)
    if not product: return jsonify({"error": "Product not found"}), 404

    active_dept = get_active_department()
    
    # Security: Only Admin or Dept Owner can edit
    if product.department_id != active_dept and g.role != 'ADMIN':
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    
    # Existing fields
    if 'name' in data: product.name = data['name']
    if 'sku' in data: product.product_code = data['sku']
    
    # ✅ NEW FIELDS
    if 'min_stock' in data: 
        try: product.min_stock = float(data['min_stock'])
        except: pass
    
    if 'max_stock' in data:
        try: product.max_stock = float(data['max_stock'])
        except: pass

    try:
        db.session.commit()
        return jsonify({"message": "Product updated"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@core.route('/transactions', methods=['GET'])
@jwt_required
def get_transactions():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    query = Transaction.query.join(Product).filter(
        Transaction.is_active == True,
    )

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d')
            end_date = end_date.replace(hour=23, minute=59, second=59)
            query = query.filter(Transaction.created_at.between(start_date, end_date))
        except ValueError:
            pass

    txns = query.order_by(desc(Transaction.created_at)).all()
    return jsonify([t.to_dict() for t in txns]), 200

# app/core/routes.py

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
    
    query = Transaction.query.filter_by(is_active=False)
    if active_dept:
        query = query.join(Product).filter(Product.department_id == active_dept)
    
    transactions = query.order_by(desc(Transaction.created_at)).all()
    return jsonify([t.to_dict() for t in transactions]), 200


@core.route('/recycle-bin/<int:id>/restore', methods=['PUT'])
@jwt_required
@admin_only
def restore_transaction(id):
    """
    Restore: Re-applies the stock change and sets is_active=True.
    """
    txn = Transaction.query.get(id)
    if not txn:
        return jsonify({"error": "Transaction not found"}), 404

    product = txn.product

    # === LOGIC: RE-APPLY STOCK CHANGE ===
    if txn.type == 'in' or txn.type == 'return':
        # Add it back
        product.current_stock += txn.quantity

    elif txn.type == 'out':
        # Remove it again
        if product.current_stock < txn.quantity:
             return jsonify({"error": "Cannot restore: Not enough stock available"}), 400
        product.current_stock -= txn.quantity

    txn.is_active = True
    
    log = ActivityLog(
        user_id=g.current_user.id, 
        action=f"Restored Transaction #{txn.id}", 
        transaction_id=txn.id
    )
    db.session.add(log)
    db.session.add(product) # Force Product Update

    db.session.commit()
    return jsonify({"message": "Transaction restored and stock updated"}), 200


@core.route('/recycle-bin/<int:id>/permanent', methods=['DELETE'])
@jwt_required
@admin_only
def permanent_delete_transaction(id):
    txn = Transaction.query.get(id)
    if not txn: return jsonify({"error": "Transaction not found"}), 404

    db.session.delete(txn)
    db.session.commit()
    return jsonify({"message": "Permanently deleted"}), 200


# ==========================================
# 4. AUXILIARY ROUTES (Employees, Depts, etc.)
# ==========================================
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
    if not data or 'name' not in data:
        return jsonify({"error": "Name is required"}), 400
    
    if Department.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Department already exists"}), 400

    new_dept = Department(name=data['name'], is_active=True)
    db.session.add(new_dept)
    db.session.commit()
    return jsonify({"message": "Department added", "department": new_dept.to_dict()}), 201

@core.route('/suppliers', methods=['GET'])
@jwt_required
def get_suppliers():
    active_dept = get_active_department()
    if g.role == "ADMIN" and not active_dept:
         suppliers = Supplier.query.filter_by(is_active=True).all()
    else:
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
@admin_only
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

@core.route('/products', methods=['POST'])
@jwt_required
def add_product():
    data = request.get_json()
    sku = data.get('sku')
    sup_name = data.get('supplier_name')
    sup_contact = data.get('supplier_contact')

    if not sup_contact: 
        return jsonify({"error": "Number needs to be provided"}), 400
    
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department context missing"}), 400

    if Product.query.filter_by(product_code=sku).first():
        return jsonify({"error": "SKU exists"}), 400
        
    if sup_name:
        sup_name = sup_name.strip()
        supplier = Supplier.query.filter(
            Supplier.name.ilike(sup_name), 
            Supplier.department_id == active_dept
        ).first()

        if not supplier:
            supplier = Supplier(
                name=sup_name, 
                phone_number=sup_contact,
                department_id=active_dept, 
                is_active=True
            )
            db.session.add(supplier)
            db.session.flush()

    new_p = Product(
        name=data['name'],
        product_code=sku,
        unit=data.get('unit'),
        category=data.get('category'),
        current_stock=float(data.get('qty', 0)),
        department_id=active_dept,
        is_active=True
    )
    db.session.add(new_p)
    db.session.commit()
    return jsonify({"message": "Product created"}), 201

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
            (Transaction.type == 'in', -Transaction.quantity), 
            else_=0
        )).label('net_qty')
    ).join(Transaction)\
     .filter(Transaction.contractor_id == id, Transaction.is_active == True)\
     .group_by(Product.id, Product.name, Product.product_code, Product.unit)\
     .having(func.sum(case(
            (Transaction.type == 'out', Transaction.quantity),
            (Transaction.type == 'in', -Transaction.quantity),
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
# app/core/routes.py

@core.route('/analytics', methods=['GET'])
@jwt_required
@admin_only
def get_analytics():
    active_dept = get_active_department()
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')
    
    # ✅ NEW: Check which specific chart data is requested
    # If None, return ALL (for backward compatibility or initial load)
    data_type = request.args.get('type') 

    # Base Filters
    filters = [Transaction.is_active == True]
    if active_dept: filters.append(Product.department_id == active_dept)
    
    # Date Filter
    if start_str and end_str:
        try:
            s = datetime.strptime(start_str, '%Y-%m-%d')
            e = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23,minute=59,second=59)
            filters.append(Transaction.created_at.between(s, e))
        except: pass

    response = {}

    # --- 1. FREQUENCY & HIGH PRESSURE ---
    if not data_type or data_type == 'frequency':
        freq_data = db.session.query(Product.name, func.count(Transaction.id).label('c'))\
            .join(Product).filter(*filters).group_by(Product.name).order_by(desc('c')).limit(10).all()
        
        # We calculate consistent pressure here too as it's related
        out_pressure_filters = filters + [Transaction.type == 'out']
        pressure_data = db.session.query(Product.name, func.count(Transaction.id).label('hits'))\
            .join(Product).filter(*out_pressure_filters).group_by(Product.name).order_by(desc('hits')).limit(5).all()

        response['frequency'] = [{"name": r[0], "count": r[1]} for r in freq_data]
        response['consistent_pressure'] = [{"name": r[0], "hits": r[1]} for r in pressure_data]

    # --- 2. TOP SOLD (STOCK OUTS) ---
    if not data_type or data_type == 'top_sold':
        out_filters = filters + [Transaction.type == 'out']
        sold_data = db.session.query(Product.name, func.sum(Transaction.quantity).label('q'))\
            .join(Product).filter(*out_filters).group_by(Product.name).order_by(desc('q')).limit(5).all()
        
        response['top_sold'] = [{"name": r[0], "qty": r[1]} for r in sold_data]

    # --- 3. TOP SUPPLIERS ---
    if not data_type or data_type == 'top_suppliers':
        in_filters = filters + [Transaction.type == 'in', Transaction.supplier_id != None]
        sup_data = db.session.query(Supplier.name, func.sum(Transaction.quantity).label('q'))\
            .join(Transaction).filter(*in_filters).group_by(Supplier.name).order_by(desc('q')).limit(5).all()
        
        response['top_suppliers'] = [{"name": r[0], "qty": r[1]} for r in sup_data]

    # --- 4. LOW STOCK (Always Return or separate? Let's keep it separate/global) ---
    if not data_type or data_type == 'low_stock':
        low_stock_query = Product.query.filter(Product.is_active == True, Product.current_stock <= Product.min_stock)
        if active_dept: low_stock_query = low_stock_query.filter(Product.department_id == active_dept)
        low_stock_items = low_stock_query.order_by(Product.current_stock.asc()).all()
        response['low_stock'] = [p.to_dict() for p in low_stock_items]

    return jsonify(response), 200