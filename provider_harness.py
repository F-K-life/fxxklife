"""Live harness for the optional OpenAI-compatible model provider.

Configuration is read only from AI_BASE_URL, AI_MODEL, and AI_API_KEY.
The API key is never printed or accepted as a command-line argument.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from modeling import chat_reply
from provider_response import assistant_json
from provider_tls import request_headers, secure_context


def chat_completions_url(base_url):
    base = (base_url or "").strip().rstrip("/")
    parsed = urlparse(base)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if not base or (parsed.scheme != "https" and not local_http):
        raise ValueError("AI_BASE_URL must use HTTPS, except for a local test server")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def parse_protocol_response(envelope):
    try:
        parsed = assistant_json(envelope)
        if (
            not isinstance(parsed, dict)
            or parsed.get("status") != "ok"
            or not isinstance(parsed.get("message"), str)
            or not parsed["message"].strip()
        ):
            raise ValueError
        return parsed
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("protocol response did not contain the required JSON assistant content") from exc


def verify_application_result(result):
    if not isinstance(result, dict):
        raise ValueError("application result was not an object")
    model = result.get("model")
    if not isinstance(model, dict) or model.get("mode") != "remote" or model.get("available") is not True:
        raise ValueError("application used its local fallback instead of the configured provider")
    if not isinstance(result.get("reply_text"), str) or not result["reply_text"].strip():
        raise ValueError("application result did not contain reply_text")
    if result.get("intent") not in {"listen", "clarify", "action", "support", "correction", "crisis"}:
        raise ValueError("application result contained an invalid intent")
    if not isinstance(result.get("evidence_ids"), list):
        raise ValueError("application result did not contain evidence_ids")
    return result


def safe_summary(base_url, model, api_key):
    key_state = "set via AI_API_KEY (value hidden)" if api_key else "missing"
    return f"endpoint={chat_completions_url(base_url)} model={model} api_key={key_state}"


def protocol_probe(base_url, model, api_key, timeout=15):
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Return one JSON object only. It must have exactly two string fields: "
                    "status and message. Set status to ok."
                ),
            },
            {"role": "user", "content": "Confirm that this chat completion request reached the model."},
        ],
    }
    request = urllib.request.Request(
        chat_completions_url(base_url),
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers(api_key),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout, context=secure_context()) as response:
        raw = response.read(131073)
    if len(raw) > 131072:
        raise ValueError("protocol response exceeded 128 KiB")
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("provider returned a non-JSON protocol response") from exc
    return parse_protocol_response(envelope)


def application_probe():
    result = chat_reply(
        "帮我把学习 Python 的计划缩小成只用 5 分钟就能开始的一步。",
        {
            "ideal": "成为能持续创造和学习的人",
            "values": "好奇心和自主选择",
            "current": "想继续学习 Python",
            "conditions": "从五分钟的小步骤开始",
            "tone": "简短、清晰、不催促",
        },
        [],
        [],
        {"feedback": []},
    )
    return verify_application_result(result)


def _preview(value, limit=180):
    compact = " ".join(str(value).split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _safe_error(exc, api_key):
    if isinstance(exc, urllib.error.HTTPError):
        return f"provider returned HTTP {exc.code}"
    if isinstance(exc, urllib.error.URLError):
        message = f"provider connection failed: {exc.reason}"
    else:
        message = str(exc) or exc.__class__.__name__
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def main():
    base_url = os.environ.get("AI_BASE_URL", "").strip()
    model = os.environ.get("AI_MODEL", "").strip()
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not base_url or not model or not api_key:
        print("FAIL: set AI_BASE_URL, AI_MODEL, and AI_API_KEY before running the harness", file=sys.stderr)
        return 2

    try:
        print("CONFIG:", safe_summary(base_url, model, api_key))
        started = time.perf_counter()
        protocol = protocol_probe(base_url, model, api_key)
        print(f"PASS protocol ({time.perf_counter() - started:.2f}s):", _preview(protocol["message"]))

        started = time.perf_counter()
        result = application_probe()
        print(f"PASS application ({time.perf_counter() - started:.2f}s):", _preview(result["reply_text"]))
        print("PASS: provider protocol and 明日见 Self Echo application integration")
        return 0
    except Exception as exc:  # The CLI must report a safe, actionable failure and exit non-zero.
        print("FAIL:", _safe_error(exc, api_key), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
