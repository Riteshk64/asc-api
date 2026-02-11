from flask import request, jsonify, g
from sqlalchemy import func
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.models.product import Product
from app.models.transaction import Transaction
from datetime import datetime
from app.extensions import db

# Import your new logic modules
from .reports import inventory, movement, partners
from . import analytics_bp

# Helper to build filters based on request
def build_filters():
    # Handle Admin context switching or User default
    if g.role == 'ADMIN':
        header_dept = request.headers.get("X-Department-Id")
        active_dept = int(header_dept) if header_dept else g.department_id
    else:
        active_dept = g.department_id

    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    # Base filters
    filters = [Transaction.is_active == True]
    
    # Filter by Department (Join Product to ensure Transaction belongs to dept)
    if active_dept:
        # Note: Ideally Transaction has department_id, otherwise join Product
        filters.append(Transaction.department_id == active_dept)
    
    # Filter by Date
    if start_str and end_str:
        try:
            s = datetime.strptime(start_str, '%Y-%m-%d')
            e = datetime.strptime(end_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            filters.append(Transaction.created_at.between(s, e))
        except: pass
        
    return filters, active_dept

@analytics_bp.route('/dashboard', methods=['GET'])
@jwt_required
@admin_only
def get_dashboard_metrics():
    filters, active_dept = build_filters()
    data_type = request.args.get('type')
    
    response = {}
    
    # ==========================================
    # 0. HIGH LEVEL STATS (Always return these)
    # ==========================================
    
    # Current Stock (Product Table)
    stock_query = Product.query.filter(Product.is_active == True)
    if active_dept:
        stock_query = stock_query.filter(Product.department_id == active_dept)
    
    total_stock = db.session.query(func.sum(Product.current_stock)).filter(
        Product.department_id == active_dept if active_dept else True
    ).scalar() or 0

    # Transactions (In, Out, Return) - Using the filters built above (Date/Dept)
    total_in = db.session.query(func.sum(Transaction.quantity)).filter(*filters).filter(Transaction.type == 'in').scalar() or 0
    total_out = db.session.query(func.sum(Transaction.quantity)).filter(*filters).filter(Transaction.type == 'out').scalar() or 0
    total_returned = db.session.query(func.sum(Transaction.quantity)).filter(*filters).filter(Transaction.type == 'return').scalar() or 0
    
    low_stock_count = Product.query.filter(
        Product.current_stock <= Product.min_stock,
        Product.department_id == active_dept if active_dept else True
    ).count()

    response.update({
        "total_stock": total_stock,
        "total_in": total_in,
        "total_out": total_out,
        "total_returned": total_returned,
        "low_stock_count": low_stock_count
    })

    # ==========================================
    # 1. Detailed Reports (Optional based on type)
    # ==========================================

    # Inventory Logic
    if not data_type or data_type == 'low_stock':
        response['low_stock'] = inventory.get_low_stock_alerts(active_dept)

    # Movement Logic (Sales/Usage)
    if not data_type or data_type == 'frequency':
        response['frequency'] = movement.get_frequency_data(filters)
        response['consistent_pressure'] = movement.get_consistent_pressure(filters)

    if not data_type or data_type == 'top_sold':
        response['top_sold'] = movement.get_top_issued_volume(filters)

    # Partners Logic (Suppliers)
    if not data_type or data_type == 'top_suppliers':
        response['top_suppliers'] = partners.get_top_suppliers(filters)
    if not data_type or data_type == 'top_stocked_in':
        response['top_stocked_in'] = movement.get_top_stocked_in(filters)

    if not data_type or data_type == 'top_contractors':
        response['top_contractors'] = partners.get_top_contractors(filters)    

    return jsonify(response), 200