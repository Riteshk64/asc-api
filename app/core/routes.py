# from flask import Blueprint, jsonify, request
# from app.extensions import db
# from app.models.product import Product  # <--- Importing from the correct models folder
# from app.models.supplier import Supplier
# from app.models.contractor import Contractor
# from app.models.transactions import StockTransaction
# from datetime import datetime
# core = Blueprint('core', __name__, url_prefix='/core')

# # # ==========================================
# # # PRODUCT ROUTES
# # # ==========================================

# # @core.route('/products', methods=['GET'])
# # def get_products():
# #     """
# #     Fetch all active products for the React Native list.
# #     """
# #     try:
# #         # Fetch only active products
# #         products = Product.query.filter_by(is_active=True).all()
# #         return jsonify([p.to_dict() for p in products]), 200
# #     except Exception as e:
# #         return jsonify({"error": str(e)}), 500
# # @core.route('/products', methods=['POST'])
# # def add_product():
# #     data = request.get_json()

# #     # 1. Basic Validation
# #     if not data or 'name' not in data or 'sku' not in data:
# #         return jsonify({"error": "Name and SKU are required"}), 400

# #     if Product.query.filter_by(product_code=data['sku']).first():
# #         return jsonify({"error": "Product SKU already exists"}), 409

# #     try:
# #         # ==================================================
# #         # LOGIC: Resolve Supplier Name -> Supplier ID
# #         # ==================================================
# #         supplier_id = None
        
# #         if data.get('supplier_name'):
# #             raw_name = data.get('supplier_name').strip()
            
# #             # Check if this supplier name ALREADY exists (Case Insensitive is safer)
# #             existing_supplier = Supplier.query.filter(Supplier.name.ilike(raw_name)).first()
            
# #             if existing_supplier:
# #                 # USE EXISTING ID
# #                 supplier_id = existing_supplier.id
# #             else:
# #                 # CREATE NEW SUPPLIER
# #                 new_supplier = Supplier(
# #                     name=raw_name,
# #                     phone=data.get('supplier_phone', ''),
# #                     contact_person=data.get('supplier_contact', '')
# #                 )
# #                 db.session.add(new_supplier)
# #                 db.session.flush() # Generates ID immediately without committing
# #                 supplier_id = new_supplier.id

# #         # ==================================================
# #         # Create Product linked to that Supplier ID
# #         # ==================================================
# #         qty = int(data.get('qty', 0))
        
# #         new_product = Product(
# #             name=data['name'],
# #             product_code=data['sku'],
# #             current_stock=qty,
# #             is_active=True,
# #             supplier_id=supplier_id # Storing the integer ID here
# #         )
# #         db.session.add(new_product)
# #         db.session.flush()

# #         # Log Initial Stock Transaction
# #         if qty > 0:
# #             txn = StockTransaction(
# #                 product_id=new_product.id,
# #                 type='in',
# #                 quantity=qty,
# #                 supplier_id=supplier_id, # Link transaction to the same supplier ID
# #                 created_at=datetime.utcnow()
# #             )
# #             db.session.add(txn)

# #         db.session.commit()

# #         return jsonify({
# #             "message": "Product added successfully", 
# #             "product": new_product.to_dict()
# #         }), 201

# #     except Exception as e:
# #         db.session.rollback()
# #         return jsonify({"error": str(e)}), 500

# # @core.route('/suppliers', methods=['GET'])
# # def get_suppliers():
# #     """
# #     Fetch all suppliers.
# #     """
# #     try:
# #         suppliers = Supplier.query.all()
# #         return jsonify([s.to_dict() for s in suppliers]), 200
# #     except Exception as e:
# #         return jsonify({"error": str(e)}), 500

# # @core.route('/suppliers', methods=['POST'])
# # def add_supplier():
# #     data = request.get_json()
    
# #     if not data or 'name' not in data:
# #         return jsonify({"error": "Supplier name is required"}), 400

# #     new_supplier = Supplier(
# #         name=data['name'],
# #         contact_person=data.get('contact', ''), # Matches React input key
# #         phone=data.get('phone', '')             # Changed from email to phone
# #     )

# #     try:
# #         db.session.add(new_supplier)
# #         db.session.commit()
# #         return jsonify({"message": "Supplier added", "supplier": new_supplier.to_dict()}), 201
# #     except Exception as e:
# #         db.session.rollback()
# #         return jsonify({"error": str(e)}), 500

# # # ==========================================
# # # 3. CONTRACTOR ROUTES
# # # ==========================================
# # @core.route('/contractors', methods=['GET'])
# # def get_contractors():
# #     """Fetch all contractors for the Contractor List screen."""
# #     contractors = Contractor.query.all()
# #     return jsonify([c.to_dict() for c in contractors]), 200

# # @core.route('/contractors', methods=['POST'])
# # def add_contractor():
# #     """Handle 'Add Contractor' modal."""
# #     data = request.get_json()
    
# #     if not data or 'name' not in data:
# #         return jsonify({"error": "Contractor name is required"}), 400

# #     new_contractor = Contractor(
# #         name=data['name'],
# #         contact_person=data.get('contact', ''),
# #         email=data.get('email', '')
# #     )

# #     try:
# #         db.session.add(new_contractor)
# #         db.session.commit()
# #         return jsonify({"message": "Contractor added", "contractor": new_contractor.to_dict()}), 201
# #     except Exception as e:
# #         db.session.rollback()
# #         return jsonify({"error": str(e)}), 500
    
# # @core.route('/stock/operate', methods=['POST'])
# # def stock_operation():
# #     """
# #     Handles Stock In (Supplier) and Stock Out (Contractor)
# #     using Names instead of IDs (Find or Create logic).
# #     """
# #     data = request.get_json()
    
# #     # 1. Validate Product
# #     product = Product.query.filter_by(product_code=data.get('sku')).first()
# #     if not product:
# #         return jsonify({"error": "Product not found"}), 404

# #     try:
# #         qty = float(data.get('qty', 0))
# #         op_type = data.get('type') # 'in' or 'out'
# #     except ValueError:
# #         return jsonify({"error": "Invalid quantity"}), 400

# #     supplier_id = None
# #     contractor_id = None

# #     # =======================================================
# #     # LOGIC: STOCK IN -> Handle Supplier
# #     # =======================================================
# #     if op_type == 'in':
# #         # Update Stock
# #         product.current_stock += qty
        
# #         # Find or Create Supplier
# #         sup_name = data.get('supplier_name')
# #         if sup_name:
# #             sup_name = sup_name.strip()
# #             supplier = Supplier.query.filter(Supplier.name.ilike(sup_name)).first()
            
# #             if not supplier:
# #                 supplier = Supplier(
# #                     name=sup_name,
# #                     phone=data.get('supplier_phone', ''),
# #                     contact_person=data.get('supplier_contact', '')
# #                 )
# #                 db.session.add(supplier)
# #                 db.session.flush() # Get ID immediately
            
# #             supplier_id = supplier.id

# #     # =======================================================
# #     # LOGIC: STOCK OUT -> Handle Contractor
# #     # =======================================================
# #     elif op_type == 'out':
# #         # Check Stock Level
# #         if product.current_stock < qty:
# #             return jsonify({"error": "Insufficient stock"}), 400
        
# #         # Update Stock
# #         product.current_stock -= qty

# #         # Find or Create Contractor
# #         cont_name = data.get('contractor_name')
# #         if cont_name:
# #             cont_name = cont_name.strip()
# #             contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
            
# #             if not contractor:
# #                 contractor = Contractor(
# #                     name=cont_name,
# #                     email=data.get('contractor_email', ''),
# #                     contact_person=data.get('contractor_contact', '')
# #                 )
# #                 db.session.add(contractor)
# #                 db.session.flush() # Get ID immediately
            
# #             contractor_id = contractor.id
    
# #     else:
# #         return jsonify({"error": "Invalid operation type. Use 'in' or 'out'"}), 400

# #     # =======================================================
# #     # 3. Log the Transaction
# #     # =======================================================
# #     txn = StockTransaction(
# #         product_id=product.id,
# #         type=op_type,
# #         quantity=qty,
# #         supplier_id=supplier_id,     # Will be None if stock out
# #         contractor_id=contractor_id, # Will be None if stock in
# #         created_at=datetime.utcnow()
# #     )

# #     try:
# #         db.session.add(txn)
# #         db.session.commit()
        
# #         return jsonify({
# #             "message": "Stock updated successfully", 
# #             "new_qty": product.current_stock,
# #             "entity": data.get('supplier_name') if op_type == 'in' else data.get('contractor_name')
# #         }), 200

# #     except Exception as e:
# #         db.session.rollback()
# #         return jsonify({"error": str(e)}), 500

# # @core.route('/stock/transactions', methods=['GET'])
# # def get_stock_transactions():
# #     """Fetch all stock history (most recent first)."""
# #     try:
# #         # Sort by date descending (newest on top)
# #         transactions = StockTransaction.query.order_by(StockTransaction.created_at.desc()).all()
# #         return jsonify([t.to_dict() for t in transactions]), 200
# #     except Exception as e:
# #         return jsonify({"error": str(e)}), 500    



# @core.route('/departments', methods=['GET'])
# def get_departments(): 
#     try: 
#         from app.models.departments import Departments
#         departments = Departments.query.all()
#         return jsonify(d.to_dict() for d in departments), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
# @core.route('departments', methods=['POST'])
# def add_department(): 
#     data = request.get_json()
#     if not data or 'name' not in data: 
#         return jsonify({"error": "Department name is required"}), 400
#     from app.models.departments import Departments
#     new_department = Departments(name = data['name'])
#     try:
#         db.session.add(new_department)
#         db.session.commit()
#         return jsonify({"messsage": "Department added", "department": new_department.to_dict()}), 201
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({"error": str(e)}), 500   


from flask import Blueprint, jsonify, request
from app.extensions import db
from sqlalchemy import desc

# Import ALL models
from app.models.department import Department
from app.models.user import User
from app.models.supplier import Supplier
from app.models.contractor import Contractor
from app.models.product import Product
from app.models.transaction import Transaction
from PIL import Image
from fuzzywuzzy import process
import pytesseract
import platform

core = Blueprint('core', __name__, url_prefix='/core')


@core.route('/stock/operate', methods=['POST'])
def stock_operation():
    data = request.get_json()
    
    sku = data.get('sku')
    op_type = data.get('type') # 'in', 'out', or 'return'
    
    # 1. Try to find the product
    product = Product.query.filter_by(product_code=sku).first()

    # 2. IF NOT FOUND: Handle creation logic
    if not product:
        if op_type == 'in':
            # We are Adding Stock -> Create the Product on the fly
            product_name = data.get('productName')
            if not product_name:
                return jsonify({"error": "Product Name is required for new products"}), 400
            
            # Create new product with 0 stock (we add the qty later below)
            product = Product(
                name=product_name,
                product_code=sku,
                current_stock=0.0,
                is_active=True
            )
            db.session.add(product)
            db.session.flush() # Generate ID immediately so we can use it
        else:
            # We are removing stock -> Error if product doesn't exist
            return jsonify({"error": "Product not found"}), 404

    # 3. Proceed with Standard Stock Logic
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
        
        # Handle Supplier (Find or Create)
        sup_name = data.get('supplier_name')
        if sup_name:
            sup_name = sup_name.strip()
            supplier = Supplier.query.filter(Supplier.name.ilike(sup_name)).first()
            if not supplier:
                supplier = Supplier(name=sup_name, is_active=True)
                db.session.add(supplier)
                db.session.flush()
            supplier_id = supplier.id

    # --- STOCK OUT ---
    elif op_type == 'out':
        if product.current_stock < qty:
            return jsonify({"error": f"Insufficient stock. Current: {product.current_stock}"}), 400
        product.current_stock -= qty

        # Handle Contractor
        cont_name = data.get('contractor_name')
        if cont_name:
            cont_name = cont_name.strip()
            contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
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
            contractor = Contractor.query.filter(Contractor.name.ilike(cont_name)).first()
            if not contractor:
                contractor = Contractor(name=cont_name, is_active=True)
                db.session.add(contractor)
                db.session.flush()
            contractor_id = contractor.id
        
        op_type = 'in' # Database records it as IN

    else:
        return jsonify({"error": "Invalid operation type"}), 400

    # 4. Save Transaction
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
def get_deleted_transactions():
    """Fetch all deleted transactions"""
    items = Transaction.query.filter_by(is_active=False).all()
    return jsonify([i.to_dict() for i in items]), 200

@core.route('/transactions/<int:id>', methods=['DELETE'])
def delete_transaction(id):
    """Soft delete a transaction"""
    txn = Transaction.query.get(id)
    if txn:
        txn.is_active = False 
        db.session.commit()
        return jsonify({"message": "Moved to recycle bin"}), 200
    return jsonify({"error": "Not found"}), 404

@core.route('/transactions/<int:id>/restore', methods=['POST'])
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
def get_departments():
    depts = Department.query.filter_by(is_active=True).all()
    return jsonify([d.to_dict() for d in depts]), 200

@core.route('/departments', methods=['POST'])
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
def get_suppliers():
    suppliers = Supplier.query.filter_by(is_active=True).all()
    return jsonify([s.to_dict() for s in suppliers]), 200

@core.route('/suppliers', methods=['POST'])
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
def get_contractors():
    contractors = Contractor.query.filter_by(is_active=True).all()
    return jsonify([c.to_dict() for c in contractors]), 200

@core.route('/contractors', methods=['POST'])
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
def get_products():
    products = Product.query.filter_by(is_active=True).all()
    return jsonify([p.to_dict() for p in products]), 200

@core.route('/products', methods=['POST'])
def add_product():
    """Simple Add Product"""
    data = request.get_json()
    if Product.query.filter_by(product_code=data.get('sku')).first():
        return jsonify({"error": "SKU exists"}), 400
        
    new_p = Product(
        name=data['name'],
        product_code=data['sku'],
        current_stock=float(data.get('qty', 0)),
        is_active=True
    )
    db.session.add(new_p)
    db.session.commit()
    return jsonify({"message": "Product created"}), 201

@core.route('/transactions', methods=['GET'])
def get_transactions():
    txns = Transaction.query.filter_by(is_active=True).order_by(desc(Transaction.created_at)).all()
    return jsonify([t.to_dict() for t in txns]), 200