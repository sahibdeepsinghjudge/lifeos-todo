from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from apps.todo.models import Todo

engine = create_engine("sqlite:///./lifeos.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

try:
    todos = db.query(Todo).all()
    print("SUCCESS, found", len(todos), "todos")
except Exception as e:
    print("FAILED:", e)
finally:
    db.close()
