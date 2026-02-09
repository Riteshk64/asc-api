from flask import Blueprint

# 1. Define the Blueprint
analytics_bp = Blueprint('analytics', __name__, url_prefix='/analytics')

# 2. Import routes (at the bottom to avoid circular import errors)
from . import routes