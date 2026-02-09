from flask import request, jsonify, g
from app.auth.jwt_middleware import jwt_required
from app.common.decorators import admin_only
from app.models.product import Product
from app.models.transaction import Transaction
from datetime import datetime

# Import your new logic modules
from .reports import inventory, movement, partners

from . import analytics_bp
from flask import jsonify

# ✅ Test Route
@analytics_bp.route('/test')
def test():
    return jsonify({"message": "Analytics Blueprint is working!"}), 200

# Helper to build filters based on request
def build_filters():
    active_dept = g.department_id if g.role != 'ADMIN' else request.headers.get("X-Department-Id")
    start_str = request.args.get('start_date')
    end_str = request.args.get('end_date')

    filters = [Transaction.is_active == True]
    
    if active_dept:
        filters.append(Product.department_id == active_dept)
    
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

    # 1. Inventory Logic
    if not data_type or data_type == 'low_stock':
        response['low_stock'] = inventory.get_low_stock_alerts(active_dept)

    # 2. Movement Logic (Sales/Usage)
    if not data_type or data_type == 'frequency':
        response['frequency'] = movement.get_frequency_data(filters)
        response['consistent_pressure'] = movement.get_consistent_pressure(filters)

    if not data_type or data_type == 'top_sold':
        response['top_sold'] = movement.get_top_issued_volume(filters)

    # 3. Partners Logic (Suppliers)
    if not data_type or data_type == 'top_suppliers':
        response['top_suppliers'] = partners.get_top_suppliers(filters)

    return jsonify(response), 200