import json
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall

raw_json = {
    "id": "call_123",
    "type": "function",
    "function": {
        "name": "test",
        "arguments": "{}"
    },
    "thought_signature": "signature_123"
}

tc = ChatCompletionMessageToolCall.model_validate(raw_json)
print("DUMP:", json.dumps(tc.model_dump(exclude_unset=True)))
print("EXTRA:", getattr(tc, 'model_extra', None))
