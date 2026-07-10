TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "apply_todo_changes",
            "description": (
                "Apply ALL of the user's requested changes in ONE call. Use this "
                "for any request that creates, updates, completes, deletes, tags, "
                "or sets recurrence on todos — especially when there is more than "
                "one change. Put everything the user asked for into a single call; "
                "do not spread changes across multiple tool calls or turns. "
                "Resolve every relative date to ISO format yourself first. "
                "Reference existing todos by the ids in the snapshot."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "create": {
                        "type": "array",
                        "description": "New todos to create.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high", "urgent"],
                                },
                                "due_date": {
                                    "type": "string",
                                    "description": "ISO format (YYYY-MM-DDTHH:MM:SS).",
                                },
                                "is_reminder": {
                                    "type": ["boolean", "string"],
                                    "description": "true for a reminder/alert.",
                                },
                                "tags": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "recurrence": {
                                    "type": "object",
                                    "description": "Optional repeat pattern for this new todo.",
                                    "properties": {
                                        "frequency": {
                                            "type": "string",
                                            "enum": ["daily", "weekly", "monthly"],
                                        },
                                        "interval": {"type": "integer"},
                                        "end_date": {"type": "string"},
                                    },
                                    "required": ["frequency"],
                                },
                                "subtasks": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Optional subtask titles for this new todo.",
                                },
                            },
                            "required": ["title"],
                        },
                    },
                    "update": {
                        "type": "array",
                        "description": "Existing todos to update (by id).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "todo_id": {"type": "integer"},
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high", "urgent"],
                                },
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                                "due_date": {"type": "string"},
                                "is_reminder": {"type": ["boolean", "string"]},
                            },
                            "required": ["todo_id"],
                        },
                    },
                    "complete": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Ids of todos to mark complete.",
                    },
                    "delete": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Ids of todos to delete.",
                    },
                    "set_recurrence": {
                        "type": "array",
                        "description": "Recurrence to set on existing todos.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "todo_id": {"type": "integer"},
                                "frequency": {
                                    "type": "string",
                                    "enum": ["daily", "weekly", "monthly"],
                                },
                                "interval": {"type": "integer"},
                                "end_date": {"type": "string"},
                            },
                            "required": ["todo_id", "frequency"],
                        },
                    },
                    "add_tag": {
                        "type": "array",
                        "description": "Tags to add to existing todos.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "todo_id": {"type": "integer"},
                                "tag_name": {"type": "string"},
                            },
                            "required": ["todo_id", "tag_name"],
                        },
                    },
                    "save_context": {
                        "type": "array",
                        "description": "Lasting facts/preferences to remember about the user.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tag": {"type": "string"},
                                "context": {"type": "string"},
                            },
                            "required": ["tag", "context"],
                        },
                    },
                    "delete_context": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags of saved notes to forget.",
                    },
                },
            },
        },
    },
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
                        "type": ["boolean", "string"],
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
                        "type": ["boolean", "string"],
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
                        "type": ["boolean", "string"],
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
                        "type": ["boolean", "string"],
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
    {
        "type": "function",
        "function": {
            "name": "get_next_date",
            "description": "Get the next date based on the current date and the number of days to add.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Number of days to add to the current date",
                    },
                },
                "required": ["days"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_user_context",
            "description": "Save personal context or preferences related to the user along with a tag. Use this to remember things about the user.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "A short tag or key describing the context (e.g., 'diet', 'work', 'location').",
                    },
                    "context": {
                        "type": "string",
                        "description": "The context or information to save about the user.",
                    },
                },
                "required": ["tag", "context"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_user_context",
            "description": "Delete a previously saved personal context or preference for the user by its tag.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tag": {
                        "type": "string",
                        "description": "The short tag or key of the context to delete (e.g., 'diet', 'work').",
                    },
                },
                "required": ["tag"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tags",
            "description": "List all existing tags/categories for the user.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user_question",
            "description": "CRITICAL INSTRUCTION: You MUST use this tool whenever you need to ask the user a question, clarify their intent, or request missing information. Do NOT ask questions in a regular text response. Always trigger this tool instead.",
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of one or more distinct questions to ask the user.",
                    },
                },
                "required": ["questions"],
            },
        },
    },
]


'''
    This file contains all the tools descriptions that will be used by the agent orchestrator to get the things done. Any new tool created will need to be added to the list in order for the agent to use it.

'''