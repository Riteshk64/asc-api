from flask import Blueprint, jsonify, request
from flask import g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only, contractor_access
from app.extensions import db
from sqlalchemy import desc

# Import ALL models
from app.models.department import Department
from app.models.supplier import Supplier
from app.models.contractor import Contractor
from app.models.product import Product
from app.models.transaction import Transaction

core = Blueprint('core', __name__, url_prefix='/core')

# ==========================================
# Helper functions
# ==========================================
def get_active_department():
    if g.role == "ADMIN":
        dept_id = request.headers.get("X-Department-Id")
        if not dept_id:
            return None
        return int(dept_id)
    return g.department_id

# ==========================================
# 1. STOCK IN/OUT ROUTES
# ==========================================
@core.route('/stock/operate', methods=['POST'])
@jwt_required
def stock_operation():
    data = request.get_json()

    sku = data.get('sku')
    op_type = data.get('type')  # 'in', 'out', 'return'

    if not sku or not op_type:
        return jsonify({"error": "SKU and operation type are required"}), 400

    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department not selected"}), 400

    # 1. Find product
    product = Product.query.filter_by(product_code=sku, is_active=True).first()

    # 2. PRODUCT NOT FOUND
    if not product:
        if op_type != 'in':
            return jsonify({"error": "Product not found"}), 404

        product_name = data.get('productName')
        if not product_name:
            return jsonify({"error": "Product Name is required for new products"}), 400

        # 🔹 Create product in ACTIVE department (CHANGED)
        product = Product(
            name=product_name,
            product_code=sku,
            current_stock=0.0,
            department_id=active_dept,
            is_active=True
        )
        db.session.add(product)
        db.session.flush()

    # 🔒 DEPARTMENT CHECK (CHANGED)
    if product.department_id != active_dept:
        return jsonify({
            "error": "You cannot operate on another department's stock"
        }), 403

    # 4. Quantity validation
    try:
        qty = float(data.get('qty', 0))
    except ValueError:
        return jsonify({"error": "Invalid quantity"}), 400

    if qty <= 0:
        return jsonify({"error": "Quantity must be positive"}), 400

    supplier_id = None
    contractor_id = None

    # --- STOCK IN ---
    if op_type == 'in':
        product.current_stock += qty

        sup_name = data.get('supplier_name')
        if sup_name:
            sup_name = sup_name.strip()
            supplier = Supplier.query.filter(
                Supplier.name.ilike(sup_name),
                Supplier.is_active == True
            ).first()

            if not supplier:
                supplier = Supplier(name=sup_name, is_active=True)
                db.session.add(supplier)
                db.session.flush()

            supplier_id = supplier.id

    # --- STOCK OUT ---
    elif op_type == 'out':
        if product.current_stock < qty:
            return jsonify({
                "error": f"Insufficient stock. Current: {product.current_stock}"
            }), 400

        product.current_stock -= qty

        cont_name = data.get('contractor_name')
        if cont_name:
            cont_name = cont_name.strip()
            contractor = Contractor.query.filter(
                Contractor.name.ilike(cont_name),
                Contractor.is_active == True
            ).first()

            if not contractor:
                contractor = Contractor(name=cont_name, is_active=True)
                db.session.add(contractor)
                db.session.flush()

            contractor_id = contractor.id

    # --- RETURN ---
    elif op_type == 'return':
        product.current_stock += qty

        cont_name = data.get('contractor_name')
        if cont_name:
            cont_name = cont_name.strip()
            contractor = Contractor.query.filter(
                Contractor.name.ilike(cont_name),
                Contractor.is_active == True
            ).first()

            if not contractor:
                contractor = Contractor(name=cont_name, is_active=True)
                db.session.add(contractor)
                db.session.flush()

            contractor_id = contractor.id

        op_type = 'in'  # Store returns as IN

    else:
        return jsonify({"error": "Invalid operation type"}), 400

    # 5. Save transaction
    txn = Transaction(
        product_id=product.id,
        type=op_type,
        quantity=qty,
        supplier_id=supplier_id,
        contractor_id=contractor_id,
        is_active=True
    )

    try:
        db.session.add(txn)
        db.session.commit()
        return jsonify({
            "message": "Stock updated successfully",
            "new_qty": product.current_stock
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# ==========================================
# 2. RECYCLE BIN ROUTES (Soft Delete)
# ==========================================
@core.route('/recycle-bin', methods=['GET'])
@jwt_required
@admin_only
def get_deleted_transactions():
    """Fetch all deleted transactions"""
    items = Transaction.query.filter_by(is_active=False).all()
    return jsonify([i.to_dict() for i in items]), 200

@core.route('/transactions/<int:id>', methods=['DELETE'])
@jwt_required
@admin_only
def delete_transaction(id):
    """Soft delete a transaction"""
    txn = Transaction.query.get(id)
    if txn:
        txn.is_active = False 
        db.session.commit()
        return jsonify({"message": "Moved to recycle bin"}), 200
    return jsonify({"error": "Not found"}), 404

@core.route('/transactions/<int:id>/restore', methods=['POST'])
@jwt_required
@admin_only
def restore_transaction(id):
    """Restore from recycle bin"""
    txn = Transaction.query.get(id)
    if txn:
        txn.is_active = True
        db.session.commit()
        return jsonify({"message": "Restored successfully"}), 200
    return jsonify({"error": "Not found"}), 404

# ==========================================
# 3. DEPARTMENT ROUTES
# ==========================================
@core.route('/departments', methods=['GET'])
@jwt_required
@admin_only
def get_departments():
    depts = Department.query.filter_by(is_active=True).all()
    return jsonify([d.to_dict() for d in depts]), 200

@core.route('/departments', methods=['POST'])
@jwt_required
@admin_only
def add_department():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Name is required"}), 400
    
    # Check duplicate
    if Department.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Department already exists"}), 400

    new_dept = Department(name=data['name'], is_active=True)
    db.session.add(new_dept)
    db.session.commit()
    return jsonify({"message": "Department added", "department": new_dept.to_dict()}), 201

# ==========================================
# 4. SUPPLIER ROUTES
# ==========================================
@core.route('/suppliers', methods=['GET'])
@jwt_required
def get_suppliers():
    suppliers = Supplier.query.filter_by(is_active=True).all()
    return jsonify([s.to_dict() for s in suppliers]), 200

@core.route('/suppliers', methods=['POST'])
@jwt_required
def add_supplier():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Name is required"}), 400
    
    if Supplier.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Supplier already exists"}), 400

    new_sup = Supplier(
        name=data['name'],
        phone_number=data.get('phone', ''),
        is_active=True
    )
    db.session.add(new_sup)
    db.session.commit()
    return jsonify({"message": "Supplier added", "supplier": new_sup.to_dict()}), 201

# ==========================================
# 5. CONTRACTOR ROUTES
# ==========================================
@core.route('/contractors', methods=['GET'])
@jwt_required
@contractor_access
def get_contractors():
    contractors = Contractor.query.filter_by(is_active=True).all()
    return jsonify([c.to_dict() for c in contractors]), 200

@core.route('/contractors', methods=['POST'])
@jwt_required
@contractor_access
def add_contractor():
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({"error": "Name is required"}), 400
    
    if Contractor.query.filter_by(name=data['name']).first():
        return jsonify({"error": "Contractor already exists"}), 400

    new_cont = Contractor(
        name=data['name'],
        phone=data.get('phone', ''),
        is_active=True
    )
    db.session.add(new_cont)
    db.session.commit()
    return jsonify({"message": "Contractor added", "contractor": new_cont.to_dict()}), 201

# ==========================================
# 6. PRODUCT & TRANSACTION LISTS
# ==========================================
@core.route('/products', methods=['GET'])
@jwt_required
def get_products():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department not selected"}), 400

    products = Product.query.filter_by(
        is_active=True,
        department_id=active_dept
    ).all()

    return jsonify([p.to_dict() for p in products]), 200

@core.route('/products', methods=['POST'])
@jwt_required
def add_product():
    """Simple Add Product"""
    data = request.get_json()
    if Product.query.filter_by(product_code=data.get('sku')).first():
        return jsonify({"error": "SKU exists"}), 400
        
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department not selected"}), 400

    new_p = Product(
        name=data['name'],
        product_code=data['sku'],
        current_stock=float(data.get('qty', 0)),
        department_id=active_dept,
        is_active=True
    )

    db.session.add(new_p)
    db.session.commit()
    return jsonify({"message": "Product created"}), 201

@core.route('/transactions', methods=['GET'])
@jwt_required
def get_transactions():
    active_dept = get_active_department()
    if not active_dept:
        return jsonify({"error": "Department not selected"}), 400

    txns = (
        Transaction.query
        .join(Product)
        .filter(
            Transaction.is_active == True,
            Product.department_id == active_dept
        )
        .order_by(desc(Transaction.created_at))
        .all()
    )

    return jsonify([t.to_dict() for t in txns]), 200
