from flask import request, jsonify, g, Blueprint
from sqlalchemy import func, case
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.models.product import Product
from app.models.transaction import Transaction
from datetime import datetime
from app.extensions import db
from .reports import inventory, movement, partners

analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

# Helper to build filters based on request
def build_filters():
    if g.role == 'ADMIN':
        header_dept = request.headers.get("X-Department-Id")
        # ✅ Safety check: ensure it's a digit and not "undefined" or "null"
        if header_dept and header_dept.isdigit():
            active_dept = int(header_dept)
        else:
            active_dept = g.department_id
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
    # 0. HIGH LEVEL STATS (Combined Query)
    # ==========================================
    
    # OPTIMIZED: Single combined query for all transaction metrics instead of 3 separate queries
    txn_stats = db.session.query(
        Transaction.type,
        func.sum(Transaction.quantity).label('total_qty')
    ).filter(*filters).group_by(Transaction.type).all()
    
    # Convert results to dict for easy lookup
    txn_dict = {row.type: float(row.total_qty or 0) for row in txn_stats}
    
    # Stock aggregation - single query
    stock_stats = db.session.query(
    func.sum(Product.current_stock).label('total_stock'),
    func.sum(
        case(
            (Product.current_stock <= Product.min_stock, 1), 
            else_=0
        )
    ).label('low_stock_count')
).filter(
    Product.is_active == True,
    Product.department_id == (active_dept if active_dept else Product.department_id)
).first()
    
    response.update({
        "total_stock": float(stock_stats.total_stock or 0) if stock_stats else 0,
        "total_in": txn_dict.get('in', 0),
        "total_out": txn_dict.get('out', 0),
        "total_returned": txn_dict.get('return', 0),
        "low_stock_count": stock_stats.low_stock_count if stock_stats else 0
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