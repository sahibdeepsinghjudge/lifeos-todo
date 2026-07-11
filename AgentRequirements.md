# OttoAI Assistant — Design

The assistant is a single RAG-first agent whose job is to help the user plan
their day. There is no classifier and no multi-agent workflow anymore.

## Flow

1. User sends a message over the `/agent/ws` WebSocket.
2. The orchestrator retrieves a snapshot of the user's data (overdue / today /
   upcoming / unscheduled tasks, tags, saved preferences) and injects it into
   the system prompt — see `agent/context.py`. This is the RAG step: most
   questions ("what should I focus on?", "what's overdue?") are answered
   directly from the snapshot with zero tool calls.
3. The assistant (`agent/assistant.py`) streams its reply. For action requests
   it may call simple, single-action tools (max 5 rounds):
   - create_todo / update_todo / complete_todo / delete_todo
   - create_subtask, set_recurrence, add_tag_to_todo, list_tags
   - mark as reminder (via `is_reminder` on create/update)
   - save_user_context / delete_user_context
   - ask_user_question (for clarification via the app's question dialog)
4. Out of scope by design: web research, multi-step workflows, bulk task
   generation. The prompt instructs the model to do the simple part and say
   so when asked for more.

## Subtask suggestions

`POST /todos/{id}/suggest-subtasks` uses the light model to propose 3–5
subtask titles for a task (see `agent/suggestions.py`). The mobile app shows
these as tappable chips on the task-details screen; nothing is persisted
until the user taps one.

## Models

Configured in `core/config.py` (`AI_PROVIDER` = groq | gemini). The main
model powers the chat assistant; the light model powers subtask suggestions.
