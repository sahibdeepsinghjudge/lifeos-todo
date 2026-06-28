from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from agent.orchestrator import run_agent

engine = create_engine("sqlite:///./lifeos.db")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

try:
    # Use user_id=1 for testing
    result = run_agent(db, 1, "Create a subtask to 'Buy milk' under todo ID 11")
    print("SUCCESS")
    print(result)
except Exception as e:
    print("FAILED:", e)
finally:
    db.close()
