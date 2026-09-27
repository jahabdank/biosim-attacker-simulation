# SPDX-License-Identifier: MIT
"""Visible-channel decoding; typed records never use the untyped envelope path."""
from __future__ import annotations

from .common import Hold, loads, require
from .source_schema import validate_fields

PRIVATE_STREAM_TYPES = {"system", "user", "thinking", "tool_call"}
ASSISTANT_FIELDS = {"type", "message", "session_id", "model_call_id", "timestamp_ms"}
RESULT_FIELDS = {"type", "result", "is_error", "request_id", "session_id", "subtype", "duration_api_ms", "duration_ms", "usage"}


def visible(data: bytes) -> dict:
    if not data.strip():
        return {"availability": "empty", "format": "empty", "text": "", "messages": []}
    try:
        value = loads(data)
    except Hold as exc:
        if exc.code != "invalid_json":
            raise
        rows = [loads(line) for line in data.splitlines() if line.strip()]
    else:
        require(isinstance(value, dict), "unknown_stdout_schema")
        if "type" not in value:
            validate_fields("terminal_response", value)
            require(isinstance(value.get("text"), str), "invalid_visible_text")
            text = value["text"]
            result = {"availability": "present" if text else "empty", "format": "json", "text": text, "messages": [text] if text else []}
            if "num_turns" in value:
                require(type(value["num_turns"]) is int and value["num_turns"] >= 0, "invalid_response_steps")
                result["num_turns"] = value["num_turns"]
            if "stopReason" in value:
                require(isinstance(value["stopReason"], str), "invalid_stop_reason")
                result["stop_reason"] = value["stopReason"]
            return result
        rows = [value]
    messages, terminal = [], []
    for row in rows:
        require(isinstance(row, dict), "unknown_stdout_schema")
        kind = row.get("type")
        if kind in PRIVATE_STREAM_TYPES:
            continue
        require(kind in {"assistant", "result"}, "unknown_stdout_event")
        if kind == "assistant":
            require(set(row).issubset(ASSISTANT_FIELDS), "unknown_assistant_envelope_field")
            message = row.get("message")
            require(isinstance(message, dict) and message.get("role") == "assistant", "invalid_assistant_message")
            require(set(message).issubset({"role", "content"}), "unknown_assistant_message_field")
            content = message.get("content")
            if isinstance(content, str):
                messages.append(content)
            else:
                require(isinstance(content, list), "invalid_assistant_content")
                for block in content:
                    require(isinstance(block, dict), "invalid_assistant_block")
                    if block.get("type") == "text":
                        require(set(block).issubset({"type", "text"}) and isinstance(block.get("text"), str), "invalid_visible_text")
                        messages.append(block["text"])
                    else:
                        require(block.get("type") in {"thinking", "reasoning", "tool_use"}, "unknown_assistant_block")
        else:
            require(set(row).issubset(RESULT_FIELDS), "unknown_result_envelope_field")
            require(isinstance(row.get("result"), str), "invalid_terminal_response")
            require("is_error" not in row or row["is_error"] is False, "stdout_terminal_error")
            require(row.get("subtype", "success") == "success", "stdout_terminal_error")
            terminal.append(row["result"])
    require(len(terminal) <= 1, "ambiguous_terminal_response")
    require(bool(terminal) or bool(messages), "missing_visible_response")
    text = terminal[0] if terminal else messages[-1]
    return {"availability": "present" if text or messages else "empty", "format": "jsonl", "text": text, "messages": messages}
