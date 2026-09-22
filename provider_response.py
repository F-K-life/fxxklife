"""Normalize JSON assistant content from OpenAI-compatible providers."""

import json
import re


_PROTOCOL_FIELD = re.compile(
    r'(?i)(?:^|[,{\s"])(reply_text|intent|action_suggestion|evidence_ids)\s*[":]'
)


def looks_structured(text):
    """Return whether visible content resembles the application's JSON protocol."""
    value = text.lstrip()
    return value.startswith(('{', '[', '```')) or bool(_PROTOCOL_FIELD.search(value[:400]))


def assistant_finish_reason(envelope):
    """Normalize the first choice completion reason without trusting its shape."""
    try:
        value = envelope['choices'][0].get('finish_reason')
        return value if isinstance(value, str) and value else 'unknown'
    except (KeyError, IndexError, TypeError):
        return 'unknown'


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
