import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    uri = os.getenv("DATABASE_URL")
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = uri or ("sqlite:///" + os.path.join(BASE_DIR, "app.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 5,
        "max_overflow": 2,
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_use_lifo": True,
        "pool_timeout": 15,
        "connect_args": { 
            "keepalives": 1,
            "keepalives_idle": 30,
            "keepalives_interval": 10,
            "keepalives_count": 5,
        }
    }
    SQLALCHEMY_SESSION_OPTIONS = {
        "expire_on_commit": False,
    }
