TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_todo",
            "description": "Create a new todo item for the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Title of the todo",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the todo",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Priority level of the todo",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Due date in ISO format (YYYY-MM-DDTHH:MM:SS)",
                    },
                    "is_reminder": {
                        "type": "boolean",
                        "description": "Set to true if this task is a reminder/alert instead of a standard todo.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of tag names to attach to the todo",
                    },
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_subtask",
            "description": "Create a subtask under an existing todo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_todo_id": {
                        "type": "integer",
                        "description": "ID of the parent todo to add a subtask to",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the subtask",
                    },
                },
                "required": ["parent_todo_id", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "complete_todo",
            "description": "Mark a todo as completed. If the todo is recurring, it will automatically create the next occurrence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "ID of the todo to complete",
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_todo",
            "description": "Update fields of an existing todo item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "ID of the todo to update",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title for the todo",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description for the todo",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "New priority level",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "description": "New status for the todo",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "New due date in ISO format (YYYY-MM-DDTHH:MM:SS)",
                    },
                    "is_reminder": {
                        "type": "boolean",
                        "description": "Set to true if this task should be converted to a reminder/alert.",
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_todo",
            "description": "Soft-delete a todo item (marks it as deleted but does not remove it permanently).",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "ID of the todo to delete",
                    },
                },
                "required": ["todo_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_todos",
            "description": "List and filter todo items. Returns todos matching the given filters.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["pending", "in_progress", "completed"],
                        "description": "Filter by status",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "urgent"],
                        "description": "Filter by priority",
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter by tag name",
                    },
                    "is_reminder": {
                        "type": "boolean",
                        "description": "Filter by whether it is a reminder (true) or standard task (false). If omitted, returns both.",
                    },
                    "due_before": {
                        "type": "string",
                        "description": "Filter todos due before this date (ISO format)",
                    },
                    "due_after": {
                        "type": "string",
                        "description": "Filter todos due after this date (ISO format)",
                    },
                    "search": {
                        "type": "string",
                        "description": "Search query to match against todo title and description",
                    },
                    "overdue": {
                        "type": "boolean",
                        "description": "If true, return only overdue todos",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_recurrence",
            "description": "Set a recurrence pattern on a todo so it repeats automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "ID of the todo to make recurring",
                    },
                    "frequency": {
                        "type": "string",
                        "enum": ["daily", "weekly", "monthly"],
                        "description": "How often the todo recurs",
                    },
                    "interval": {
                        "type": "integer",
                        "description": "Interval between recurrences (e.g., 2 for every 2 weeks). Defaults to 1.",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "When the recurrence ends (ISO format). If omitted, recurs indefinitely.",
                    },
                },
                "required": ["todo_id", "frequency"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_tag_to_todo",
            "description": "Add a tag to a todo item. Creates the tag if it does not already exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "todo_id": {
                        "type": "integer",
                        "description": "ID of the todo to tag",
                    },
                    "tag_name": {
                        "type": "string",
                        "description": "Name of the tag to add",
                    },
                },
                "required": ["todo_id", "tag_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_overdue_todos",
            "description": "Get all overdue todos (past due date and not completed).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_summary",
            "description": "Get a summary of all todos, including counts by status and priority.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_today",
            "description": "Get today's date.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


'''
    This file contains all the tools descriptions that will be used by the agent orchestrator to get the things done. Any new tool created will need to be added to the list in order for the agent to use it.

'''