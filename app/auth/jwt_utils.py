import os
import jwt
from datetime import datetime, timedelta
from flask import current_app

def generate_jwt(payload, expires_in_minutes=60):
    payload["exp"] = datetime.utcnow() + timedelta(minutes=expires_in_minutes)
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm=os.getenv("ALGORITHM"))
