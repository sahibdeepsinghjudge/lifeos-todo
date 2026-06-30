from __future__ import annotations

import json
from datetime import datetime

from core.config import IST


from sqlalchemy.orm import Session

from apps.todo import service as todo_service
from apps.todo.schemas import TodoCreate, TodoUpdate, SubtaskCreate, RecurrenceCreate
from apps.tags import service as tag_service


def handle_tool_call(tool_name: str, arguments: dict, db: Session, user_id: int) -> str:
    """Dispatch a tool call to the appropriate service function. Returns JSON string result."""

    if tool_name == "create_todo":
        # Extract tags if provided
        tag_names = arguments.pop("tags", [])
        # Parse due_date if string
        if arguments.get("due_date"):
            arguments["due_date"] = datetime.fromisoformat(arguments["due_date"])
        data = TodoCreate(**arguments)
        todo = todo_service.create_todo(db, user_id, data)
        # Attach tags
        for tag_name in tag_names or []:
            tag = tag_service.get_or_create_tag(db, user_id, tag_name)
            todo_service.add_tag_to_todo(db, user_id, todo.id, tag.id)
        return json.dumps({"id": todo.id, "title": todo.title, "status": "created"})

    elif tool_name == "create_subtask":
        parent_id = arguments["parent_todo_id"]
        data = SubtaskCreate(title=arguments["title"])
        subtask = todo_service.create_subtask(db, user_id, parent_id, data)
        return json.dumps({"id": subtask.id, "title": subtask.title, "parent_id": parent_id})

    elif tool_name == "complete_todo":
        result = todo_service.complete_todo(db, user_id, arguments["todo_id"])
        resp: dict = {"id": result["todo"].id, "status": "completed"}
        if result.get("next_occurrence"):
            resp["next_occurrence_id"] = result["next_occurrence"].id
        return json.dumps(resp)

    elif tool_name == "update_todo":
        todo_id = arguments.pop("todo_id")
        if arguments.get("due_date"):
            arguments["due_date"] = datetime.fromisoformat(arguments["due_date"])
        data = TodoUpdate(**arguments)
        todo = todo_service.update_todo(db, user_id, todo_id, data)
        return json.dumps({"id": todo.id, "title": todo.title, "status": "updated"})

    elif tool_name == "delete_todo":
        todo_service.delete_todo(db, user_id, arguments["todo_id"])
        return json.dumps({"status": "deleted", "id": arguments["todo_id"]})

    elif tool_name == "list_todos":
        # Remap 'status' to 'status_filter' to match service signature
        if "status" in arguments:
            arguments["status_filter"] = arguments.pop("status")
        # Parse date strings
        if arguments.get("due_before"):
            arguments["due_before"] = datetime.fromisoformat(arguments["due_before"])
        if arguments.get("due_after"):
            arguments["due_after"] = datetime.fromisoformat(arguments["due_after"])
        todos = todo_service.list_todos(db, user_id, **arguments)
        return json.dumps([
            {
                "id": t.id,
                "title": t.title,
                "priority": t.priority,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t in todos
        ])

    elif tool_name == "set_recurrence":
        todo_id = arguments.pop("todo_id")
        if arguments.get("end_date"):
            arguments["end_date"] = datetime.fromisoformat(arguments["end_date"])
        data = RecurrenceCreate(**arguments)
        rec = todo_service.set_recurrence(db, user_id, todo_id, data)
        return json.dumps({"id": rec.id, "frequency": rec.frequency, "interval": rec.interval})

    elif tool_name == "add_tag_to_todo":
        tag = tag_service.get_or_create_tag(db, user_id, arguments["tag_name"])
        todo_service.add_tag_to_todo(db, user_id, arguments["todo_id"], tag.id)
        return json.dumps({"status": "tagged", "tag": tag.name})

    elif tool_name == "get_overdue_todos":
        todos = todo_service.list_todos(db, user_id, overdue=True)
        return json.dumps([
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "priority": t.priority,
            }
            for t in todos
        ])

    elif tool_name == "get_summary":
        todos = todo_service.list_todos(db, user_id)
        summary: dict = {"total": len(todos), "by_status": {}, "by_priority": {}}
        for t in todos:
            summary["by_status"][t.status] = summary["by_status"].get(t.status, 0) + 1
            summary["by_priority"][t.priority] = summary["by_priority"].get(t.priority, 0) + 1
        return json.dumps(summary)

    elif tool_name == "get_today":
        date = datetime.now(IST).date()
        date_str = date.isoformat()
        return json.dumps({"today": date_str})
    
    elif tool_name == "get_next_date":
        date = datetime.now(IST).date()
        next_date = date + timedelta(days=arguments['days'])
        next_date_str = next_date.isoformat()
        return json.dumps({"next_date": next_date_str})

    elif tool_name == "save_user_context":
        from apps.auth.models import User
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return json.dumps({"error": "User not found"})
        
        prefs = {}
        if user.preferences:
            try:
                prefs = json.loads(user.preferences)
            except json.JSONDecodeError:
                pass
        
        tag = arguments.get("tag", "general")
        context = arguments.get("context", "")
        prefs[tag] = context
        
        user.preferences = json.dumps(prefs)
        db.commit()
        return json.dumps({"success": True, "tag": tag, "context": context})

    elif tool_name == "delete_user_context":
        tag = arguments.get("tag")
        prefs = {}
        if user.preferences:
            try:
                prefs = json.loads(user.preferences)
            except:
                pass
        
        if tag in prefs:
            del prefs[tag]
            user.preferences = json.dumps(prefs)
            db.commit()
            return json.dumps({"success": True, "tag": tag, "message": "Context deleted successfully."})
        return json.dumps({"success": False, "message": f"Context with tag '{tag}' not found."})

    elif tool_name == "list_tags":
        from apps.tags.service import list_tags
        tags = list_tags(db, user_id)
        return json.dumps([
            {"id": t.id, "name": t.name, "color": t.color}
            for t in tags
        ])
        
    elif tool_name == "ask_user_question":
        return json.dumps({"status": "Question sent to user via dialog box. Do not output anything else. Stop and wait for their reply."})
        
    else:
        return json.dumps({"error": f"Unknown tool: {tool_name}"})
