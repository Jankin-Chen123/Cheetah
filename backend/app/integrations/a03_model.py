"""Pi custom stream transport using the existing configurable structured model endpoint."""

import json

import httpx

from app.core.config import Settings
from app.modules.intake.analysis import model_ready


def chat_messages(messages: list) -> list[dict]:
    result = []
    for message in messages:
        role = message["role"]
        content = message.get("content", [])
        if role == "system":
            text = (
                content
                if isinstance(content, str)
                else "\n".join(
                    part.get("text", "") for part in content if part.get("type") == "text"
                )
            )
            text += "\n" + "\n".join(
                value for value in message.get("sections", {}).values() if value
            )
            result.append({"role": "system", "content": text})
        elif role == "user":
            result.append(
                {
                    "role": "user",
                    "content": content
                    if isinstance(content, str)
                    else [part for part in content if part.get("type") == "text"],
                }
            )
        elif role == "assistant":
            calls = [part for part in content if part["type"] == "toolCall"]
            assistant = {
                "role": "assistant",
                "content": "\n".join(part["text"] for part in content if part["type"] == "text")
                or None,
            }
            if calls:
                assistant["tool_calls"] = [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"], ensure_ascii=False),
                        },
                    }
                    for call in calls
                ]
            result.append(assistant)
        elif role == "toolResult":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": message["toolCallId"],
                    "content": "\n".join(
                        part["text"] for part in content if part["type"] == "text"
                    ),
                }
            )
        else:
            raise ValueError("Unsupported Pi transcript role")
    return result


def invoke_research_model(settings: Settings, request: dict, request_id: str) -> tuple[dict, int]:
    model_ready(settings)
    with httpx.Client(timeout=settings.model_timeout_seconds, follow_redirects=False) as client:
        with client.stream(
            "POST",
            settings.model_endpoint,
            headers={
                "Authorization": "Bearer " + settings.model_api_key.get_secret_value(),
                "Idempotency-Key": request_id,
            },
            json={
                "model": settings.model_name,
                "messages": chat_messages(request["messages"]),
                "tools": [
                    {"type": "function", "function": definition} for definition in request["tools"]
                ],
                "tool_choice": "auto",
                "parallel_tool_calls": False,
                "max_tokens": settings.model_max_output_tokens,
                "temperature": 0,
            },
        ) as response:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 1_000_000:
                    raise ValueError("Model response exceeded limit")
                chunks.append(chunk)
    payload = json.loads(b"".join(chunks))
    message = payload["choices"][0]["message"]
    tokens = payload.get("usage", {}).get("total_tokens", 0)
    tokens = (
        tokens if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0 else 0
    )
    content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
    for call in message.get("tool_calls", []):
        content.append(
            {
                "type": "toolCall",
                "id": call["id"],
                "name": call["function"]["name"],
                "arguments": json.loads(call["function"]["arguments"]),
            }
        )
    return {
        "role": "assistant",
        "content": content,
        "api": "openai-completions",
        "provider": "cheetah-host",
        "model": settings.model_name,
        "stopReason": "toolUse" if message.get("tool_calls") else "stop",
        "usage": {
            "input": 0,
            "output": 0,
            "cacheRead": 0,
            "cacheWrite": 0,
            "totalTokens": tokens,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0},
        },
        "timestamp": 0,
    }, tokens
