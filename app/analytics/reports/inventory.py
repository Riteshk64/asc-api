from app.models.product import Product

def get_low_stock_alerts(active_dept=None):
    query = Product.query.filter(
        Product.is_active == True,
        Product.min_stock != None,
        Product.current_stock <= Product.min_stock
    )

    if active_dept:
        query = query.filter(Product.department_id == active_dept)

    items = query.order_by(Product.current_stock.asc()).all()

    return [
        {
            "id": p.id,
            "name": p.name,
            "qty": p.current_stock,
            "min_stock": p.min_stock
        }
        for p in items
    ]
