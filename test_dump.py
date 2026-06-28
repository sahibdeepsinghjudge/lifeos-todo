import json
from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

tc = ChatCompletionMessageToolCall(
    id="call_123",
    type="function",
    function=Function(name="test", arguments="{}")
)

print(json.dumps(tc.model_dump(exclude_unset=True)))
