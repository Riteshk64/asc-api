from app.extensions import db
from app.models.product import Product
from sqlalchemy import desc

def get_low_stock_alerts(active_dept=None):
    query = Product.query.filter(Product.is_active == True, Product.current_stock <= Product.min_stock)
    
    if active_dept:
        query = query.filter(Product.department_id == active_dept)
        
    items = query.order_by(Product.current_stock.asc()).all()
    return [p.to_dict() for p in items]

