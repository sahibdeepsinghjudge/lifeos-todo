import sys
from datetime import datetime, timedelta
from sqlalchemy.orm import sessionmaker
from apps.auth.models import User
from apps.todo.models import Todo, TodoRecurrence, PriorityEnum, StatusEnum, FrequencyEnum
from apps.todo.service import complete_todo
from apps.todo.router import _todo_to_response
from core.database import Base, engine, SessionLocal

db = SessionLocal()

user = db.query(User).first()

todo = Todo(
    user_id=user.id,
    title="Test Response",
    priority=PriorityEnum.medium.value,
    status=StatusEnum.pending.value,
    due_date=datetime.now()
)
db.add(todo)
db.commit()
db.refresh(todo)

recur = TodoRecurrence(
    todo_id=todo.id,
    frequency=FrequencyEnum.daily.value,
    interval=1,
    next_occurrence=datetime.now() + timedelta(days=1)
)
db.add(recur)

sub = Todo(
    user_id=user.id,
    parent_id=todo.id,
    title="Subtask Resp",
    priority=PriorityEnum.medium.value,
    status=StatusEnum.pending.value
)
db.add(sub)
db.commit()

res = complete_todo(db, user.id, todo.id)
next_todo = res["next_occurrence"]

resp = _todo_to_response(db, next_todo)
print(f"Subtasks in response: {len(resp.subtasks)}")

