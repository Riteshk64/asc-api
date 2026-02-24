import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    uri = os.getenv("DATABASE_URL")
    if uri and uri.startswith("postgres://"):
        uri = uri.replace("postgres://", "postgresql://", 1)
    
    SQLALCHEMY_DATABASE_URI = uri or ("sqlite:///" + os.path.join(BASE_DIR, "app.db"))
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    #delete before pushing to production
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,  
        "pool_recycle": 300,   
    }
