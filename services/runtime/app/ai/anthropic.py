"""The `anthropic` provider: the Anthropic Messages API as the backup when our own server (the Spark) cannot answer.

    AI_PROVIDERS=spark,anthropic       # the server's own models first, Anthropic second (owner's decision, 11 Nov 2026)

Settings: ANTHROPIC_API_KEY (no key: left out of the chain), ANTHROPIC_MODEL (default `claude-haiku-5-5`, the cheap
vision model), ANTHROPIC_VERIFY_MODEL (the Verifier's model when it runs here; default ANTHROPIC_MODEL),
ANTHROPIC_BASE (default https://api.anthropic.com/v1), ANTHROPIC_VERSION (the `anthropic-version` header, default
2026-10-21), ANTHROPIC_MAX_TOKENS (default 4096). Timeouts as every provider: ANTHROPIC_CONNECT_S,
ANTHROPIC_FIRST_TOKEN_S, ANTHROPIC_REQUEST_S.

Every caller already builds an OpenAI-style chat-completions body for the hosted providers. This module translates
that body into a Messages API request and the reply back into the chat-completions shape, so each call site only
swaps the POST (`post_chat`, `stream_chat`) and keeps its own parsing, timeouts and failover:

* system turns -> `system`; user/assistant turns -> `messages` (consecutive turns of one role merged);
* an `image_url` data URL -> an `image` block with a base64 source (JPEG, PNG, GIF, WebP); a PDF data URL -> a
  `document` block; any other URL -> a `url` source;
* `response_format` json_schema -> `output_config.format` json_schema (structured outputs, no beta header), with the
  constraint keywords the API does not take removed. If the API refuses the schema (HTTP 400) the request is sent
  once more without it, the schema then given in the system prompt: the reply is still parsed and validated by code;
* `reasoning_effort` -> `output_config.effort`; `temperature` is never sent (version 2026-10-21 refuses it);
* the reply's text blocks -> `choices[0].message.content`; its usage -> `prompt_tokens` / `completion_tokens`.

Checked against platform.claude.com on 11 Nov 2026 (models overview, versioning, structured outputs, effort, Messages
API reference). Usage is logged as token counts only: never the prompt, the document or the reply. The key goes only
in the `x-api-key` header and is never logged, serialised or put in an error.

Zero data retention is not on by default for an Anthropic organisation (it is arranged with Anthropic's sales team);
without it, Anthropic deletes API inputs and outputs within 30 days unless its usage policy or the law needs them
longer. Its Commercial Terms say it may not train models on customer content.
"""

from __future__ import annotations

import copy
import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from app.ai.config import AiConfig

log = logging.getLogger("accnomos.ai")

DEFAULT_BASE = "https://api.anthropic.com/v1"
DEFAULT_MODEL = "claude-haiku-5-5"
DEFAULT_VERSION = "2026-10-21"
DEFAULT_MAX_TOKENS = 4096
IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
#: JSON Schema keywords structured outputs does not take (the SDK helpers strip them too); code validates them after.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "title",
    }
)


def is_anthropic(cfg: AiConfig) -> bool:
    """True for the real Anthropic provider (test mode points every provider at the stub AI instead)."""
    return cfg.provider == "anthropic" and cfg.mode == "key"


def max_tokens(env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    try:
        return max(256, int(env.get("ANTHROPIC_MAX_TOKENS") or DEFAULT_MAX_TOKENS))
    except ValueError:
        return DEFAULT_MAX_TOKENS


def version(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return (env.get("ANTHROPIC_VERSION") or "").strip() or DEFAULT_VERSION


def verify_model(env: Mapping[str, str] | None = None) -> str | None:
    env = os.environ if env is None else env
    return (env.get("ANTHROPIC_VERIFY_MODEL") or "").strip() or None


# --------------------------------------------------------------------------- #
# Request translation
# --------------------------------------------------------------------------- #


def clean_schema(schema: Any) -> Any:
    """A copy of `schema` without the keywords structured outputs refuses."""
    if isinstance(schema, dict):
        return {k: clean_schema(v) for k, v in schema.items() if k not in UNSUPPORTED_KEYWORDS}
    if isinstance(schema, list):
        return [clean_schema(v) for v in schema]
    return copy.deepcopy(schema)


def _data_url(url: str) -> tuple[str, str] | None:
    """(media type, base64 data) of a `data:<type>;base64,<data>` URL, else None."""
    if not url.startswith("data:") or ";base64," not in url:
        return None
    head, data = url[5:].split(";base64,", 1)
    return head.split(";")[0].strip().lower(), data


def _block(part: Any) -> dict[str, Any] | None:
    """One chat-completions content part as a Messages API content block."""
    if isinstance(part, str):
        return {"type": "text", "text": part}
    if not isinstance(part, dict):
        return None
    kind = part.get("type")
    if kind == "text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if kind == "image_url":
        raw = part.get("image_url")
        url = raw.get("url") if isinstance(raw, dict) else raw
        if not isinstance(url, str):
            return None
        parsed = _data_url(url)
        if parsed is None:
            return {"type": "image", "source": {"type": "url", "url": url}}
        media, data = parsed
        if media == "application/pdf":
            return {"type": "document", "source": {"type": "base64", "media_type": media, "data": data}}
        if media == "image/jpg":
            media = "image/jpeg"
        return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}
    if kind == "file":  # chat-completions PDF part: {"type": "file", "file": {"file_data": "data:application/pdf..."}}
        raw = part.get("file") or {}
        parsed = _data_url(str(raw.get("file_data") or "")) if isinstance(raw, dict) else None
        if parsed is not None and parsed[0] == "application/pdf":
            return {"type": "document", "source": {"type": "base64", "media_type": parsed[0], "data": parsed[1]}}
    return None


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(p.get("text") or "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [b for p in content if (b := _block(p)) is not None]
    return []


def to_messages_body(body: Mapping[str, Any], cfg: AiConfig, *, structured: bool = True) -> dict[str, Any]:
    """A chat-completions request body as a Messages API one. `structured=False` leaves out `output_config.format` and
    gives the schema in the system prompt instead (the retry after the API refused a schema)."""
    system: list[str] = []
    turns: list[dict[str, Any]] = []
    for m in body.get("messages") or []:
        role = m.get("role")
        if role in ("system", "developer"):
            if text := _text_of(m.get("content")):
                system.append(text)
            continue
        if role not in ("user", "assistant"):
            continue
        blocks = _blocks(m.get("content"))
        if not blocks:
            continue
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})
    if not turns or turns[0]["role"] != "user":  # the Messages API starts with the user's turn
        turns.insert(0, {"role": "user", "content": [{"type": "text", "text": "(The conversation so far.)"}]})
    out: dict[str, Any] = {
        "model": body.get("model") or cfg.model,
        "max_tokens": int(body.get("max_tokens") or body.get("max_completion_tokens") or max_tokens()),
        "messages": turns,
    }
    output_config: dict[str, Any] = {}
    fmt = body.get("response_format")
    schema = None
    if isinstance(fmt, dict) and fmt.get("type") == "json_schema":
        schema = (fmt.get("json_schema") or {}).get("schema")
    if isinstance(schema, dict):
        if structured:
            output_config["format"] = {"type": "json_schema", "schema": clean_schema(schema)}
        else:
            system.append(
                "Reply with one JSON object only, no other text, matching this JSON Schema:\n"
                + json.dumps(schema, separators=(",", ":"))
            )
    elif isinstance(fmt, dict) and fmt.get("type") == "json_object":
        system.append("Reply with one JSON object only, no other text.")
    effort = body.get("reasoning_effort")
    if effort in ("low", "medium", "high"):
        output_config["effort"] = effort
    if output_config:
        out["output_config"] = output_config
    if system:
        out["system"] = "\n\n".join(system)
    if body.get("stream"):
        out["stream"] = True
    return out


def headers(cfg: AiConfig) -> dict[str, str]:
    """The request headers: the key, the API version, JSON. Never logged."""
    return {**cfg.auth_headers(), "content-type": "application/json"}


# --------------------------------------------------------------------------- #
# Reply translation
# --------------------------------------------------------------------------- #


def usage_of(data: Mapping[str, Any]) -> dict[str, Any]:
    """The Messages API's usage in the chat-completions keys the other providers report."""
    u = data.get("usage") or {}
    if not isinstance(u, dict):
        return {}
    prompt = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
    prompt += u.get("cache_creation_input_tokens") or 0
    done = u.get("output_tokens") or 0
    return {"prompt_tokens": prompt, "completion_tokens": done, "total_tokens": prompt + done}


def to_openai(data: Mapping[str, Any]) -> dict[str, Any]:
    """A Messages API reply as a chat-completions one (text blocks joined; thinking blocks dropped)."""
    text = "".join(
        str(b.get("text") or "") for b in data.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"
    )
    stop = data.get("stop_reason")
    finish = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "refusal": "content_filter"}
    return {
        "id": data.get("id"),
        "object": "chat.completion",
        "model": data.get("model"),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish.get(str(stop), str(stop) if stop else "stop"),
            }
        ],
        "usage": usage_of(data),
    }


def _log_usage(cfg: AiConfig, usage: Mapping[str, Any], *, retried: bool = False) -> None:
    """Token counts only (as extract.py's metadata for the other providers): nothing of the request or the reply."""
    log.info(
        "AI usage: provider=anthropic model=%s prompt_tokens=%s completion_tokens=%s%s",
        cfg.model,
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        " (sent again without the schema)" if retried else "",
    )


def _schema_refused(r: httpx.Response, sent: Mapping[str, Any]) -> bool:
    return r.status_code == 400 and "format" in (sent.get("output_config") or {})


# --------------------------------------------------------------------------- #
# Calls
# --------------------------------------------------------------------------- #


async def post_chat(client: httpx.AsyncClient, cfg: AiConfig, body: Mapping[str, Any]) -> httpx.Response:
    """POST a chat-completions body to the Messages API; the reply comes back in the chat-completions shape (the
    status and the request kept, so `raise_for_status` and the chain's failover rules work unchanged). An error reply
    is returned as the API sent it."""
    payload = to_messages_body({**body, "stream": False}, cfg)
    r = await client.post(f"{cfg.base_url}/messages", json=payload, headers=headers(cfg))
    retried = False
    if _schema_refused(r, payload):
        log.warning("anthropic refused the JSON schema (HTTP 400); sending again with the schema in the prompt")
        payload = to_messages_body({**body, "stream": False}, cfg, structured=False)
        r = await client.post(f"{cfg.base_url}/messages", json=payload, headers=headers(cfg))
        retried = True
    if r.is_error:
        return r
    try:
        data = r.json()
    except ValueError:
        raise httpx.DecodingError("anthropic returned something that isn't JSON", request=r.request) from None
    if not isinstance(data, dict):
        raise httpx.DecodingError("anthropic returned an unexpected reply", request=r.request)
    shaped = to_openai(data)
    _log_usage(cfg, shaped["usage"], retried=retried)
    return httpx.Response(r.status_code, json=shaped, request=r.request)


async def stream_chat(
    client: httpx.AsyncClient,
    cfg: AiConfig,
    body: Mapping[str, Any],
    lines: Any,
) -> AsyncIterator[str]:
    """The reply's text as it arrives (server-sent events: `content_block_delta` / `text_delta`). `lines(response)`
    yields the response's lines with the caller's waits (app/ai/ask.py `_lines`). An `error` event before any text
    (e.g. `overloaded_error`) raises so the chain fails over; HTTP errors raise as httpx's."""
    from app.ai.chain import ProviderDown  # late: chain imports ask, which imports this module

    payload = to_messages_body({**body, "stream": True}, cfg)
    for attempt in (1, 2):
        async with client.stream("POST", f"{cfg.base_url}/messages", json=payload, headers=headers(cfg)) as r:
            if r.is_error:
                await r.aread()
                if attempt == 1 and _schema_refused(r, payload):
                    log.warning("anthropic refused the JSON schema (HTTP 400); sending again with it in the prompt")
                    payload = to_messages_body({**body, "stream": True}, cfg, structured=False)
                    continue
                r.raise_for_status()
            usage: dict[str, Any] = {}
            async for line in lines(r):
                if not line.startswith("data:"):
                    continue
                try:
                    event = json.loads(line.removeprefix("data:").strip())
                except ValueError:
                    raise httpx.DecodingError(f"unreadable event: {line[:80]!r}") from None
                if not isinstance(event, dict):
                    continue
                kind = event.get("type")
                if kind == "message_start":
                    usage |= (event.get("message") or {}).get("usage") or {}
                elif kind == "message_delta":
                    usage |= event.get("usage") or {}
                elif kind == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta" and (text := delta.get("text")):
                        yield str(text)
                elif kind == "error":
                    err = event.get("error") or {}
                    raise ProviderDown(f"anthropic stream error: {err.get('type') or 'error'}")
                elif kind == "message_stop":
                    break
            _log_usage(cfg, usage_of({"usage": usage}), retried=attempt == 2)
            return


async def post_openai(
    client: httpx.AsyncClient, cfg: AiConfig, body: Mapping[str, Any], hdrs: Mapping[str, str]
) -> httpx.Response:
    """The hosted-provider POST every call site makes: `{base}/chat/completions` with `hdrs`, or, for the Anthropic
    provider, the Messages API through `post_chat` (its own headers, not `hdrs`). Either way the reply is
    chat-completions shaped."""
    if is_anthropic(cfg):
        return await post_chat(client, cfg, body)
    return await client.post(f"{cfg.base_url}/chat/completions", json=dict(body), headers=dict(hdrs))
