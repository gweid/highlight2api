import json
from typing import List, Dict, Any, Optional

from .models import Message, OpenAITool


def format_messages_to_prompt(messages: List[Message]) -> str:
    """将OpenAI格式的消息转换为单个提示字符串"""
    formatted_messages = []
    for message in messages:
        if message.role:
            if message.content:
                if isinstance(message.content, list):
                    for item in message.content:
                        formatted_messages.append(f"{message.role}: {item.text}")
                else:
                    formatted_messages.append(f"{message.role}: {message.content}")
            if message.tool_calls:
                formatted_messages.append(
                    f"{message.role}: {json.dumps(message.tool_calls)}"
                )
            if message.tool_call_id:
                formatted_messages.append(
                    f"{message.role}: tool_call_id: {message.tool_call_id} {message.content}"
                )
    return "\n\n".join(formatted_messages)


def format_openai_tools(tools: Optional[List[OpenAITool]]) -> List[Dict[str, Any]]:
    """将OpenAI格式的工具转换为Highlight格式"""
    if not tools:
        return []

    highlight_tools = []
    for tool in tools:
        if tool.type == "function":
            highlight_tool = {
                "name": tool.function.name,
                "description": tool.function.description or "",
                "parameters": tool.function.parameters or {}
            }
            highlight_tools.append(highlight_tool)

    return highlight_tools
