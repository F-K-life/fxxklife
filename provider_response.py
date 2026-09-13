"""Normalize JSON assistant content from OpenAI-compatible providers."""

import json
import re


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        for key in ("text", "content", "value"):
            value = content.get(key)
            if isinstance(value, str):
                return value
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def _json_object(text):
    cleaned = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.I)
    try:
        value = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        decoder = json.JSONDecoder()
        for match in re.finditer(r"[\{\[]", cleaned):
            try:
                value, _ = decoder.raw_decode(cleaned[match.start():])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise ValueError("assistant content did not contain a JSON object")
    if not isinstance(value, dict):
        raise ValueError("assistant content was not a JSON object")
    return value


def assistant_json(envelope):
    """Return the first assistant JSON object across common compatible shapes."""
    try:
        message = envelope["choices"][0]["message"]
        content = message.get("content")
        text = _content_text(content)
        if not text:
            text = _content_text(message.get("reasoning_content"))
        return _json_object(text)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("provider response did not contain JSON assistant content") from exc


def assistant_text(envelope):
    """Return visible assistant text from common compatible response shapes."""
    try:
        message = envelope["choices"][0]["message"]
        text = _content_text(message.get("content"))
        if not text:
            text = _content_text(message.get("reasoning_content"))
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.I | re.S).strip()
        if not text:
            raise ValueError("empty assistant content")
        return text
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("provider response did not contain assistant text") from exc
