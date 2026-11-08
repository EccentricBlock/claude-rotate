"""OpenAI chat.completions <-> Anthropic /v1/messages translation (Phase 3).

Pure functions + one incremental SSE translator, deliberately import-safe with no
config dependency so they can be unit-tested offline (rotator.py needs config.json
at import; this module needs nothing).

Scope: text conversations. Tool use is REFUSED loudly (400) rather than
mistranslated silently: the schemas differ and a wrong translation would look
like a model failure to the caller.
"""
from __future__ import annotations

import codecs
import json
import time

_FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}


def _oai_usage(u: dict) -> dict:
    """OpenAI counts the whole prompt; Anthropic splits cache reads/writes out.
    Folding them into prompt_tokens keeps any caller-side cost math sane."""
    prompt = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
              + u.get("cache_creation_input_tokens", 0))
    out = u.get("output_tokens", 0)
    return {"prompt_tokens": prompt, "completion_tokens": out,
            "total_tokens": prompt + out}


def oai_to_anthropic(oai: dict) -> tuple[dict | None, str | None]:
    """OpenAI body -> Anthropic body, or (None, error). System/developer messages
    become the `system` param; consecutive same-role messages are merged because
    Anthropic requires alternation."""
    if not isinstance(oai, dict):
        return None, "body must be a JSON object"
    if oai.get("tools") or oai.get("functions") or oai.get("tool_choice"):
        return None, "tool use is not supported by this endpoint yet"
    messages = oai.get("messages")
    if not isinstance(messages, list):
        return None, "messages must be an array"
    max_tokens = oai.get("max_tokens")
    if max_tokens is None:
        max_tokens = oai.get("max_completion_tokens")
    if max_tokens is None:
        max_tokens = 4096
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
        return None, "max_tokens/max_completion_tokens must be a positive integer"
    system_parts: list[str] = []
    msgs: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            return None, "each messages[] entry must be an object"
        role, content = m.get("role"), m.get("content")
        if m.get("tool_calls") or m.get("function_call"):
            return None, "tool calls are not supported by this endpoint yet"
        if isinstance(content, list):        # OpenAI content-part arrays
            for p in content:
                if not isinstance(p, dict):
                    return None, "each content part must be an object"
                if p.get("type") != "text":
                    return None, (f"unsupported content part type: {p.get('type')!r}; "
                                  "this endpoint takes text only")
            text_parts = [p.get("text", "") for p in content]
            if any(not isinstance(text, str) for text in text_parts):
                return None, "text content parts must contain strings"
            content = "".join(text_parts)
        content = "" if content is None else str(content)
        if role in ("system", "developer"):
            system_parts.append(content)
        elif role in ("user", "assistant"):
            if msgs and msgs[-1]["role"] == role:
                msgs[-1]["content"].append(content)
            else:
                msgs.append({"role": role, "content": [content]})
        else:
            return None, f"unsupported message role: {role!r}"
    if not msgs:
        return None, "messages[] must contain at least one user/assistant message"
    out: dict = {
        "model": oai.get("model"),
        "max_tokens": max_tokens,
        "messages": [{"role": m["role"], "content": "\n\n".join(m["content"])} for m in msgs],
        "stream": bool(oai.get("stream")),
    }
    if system_parts:
        out["system"] = "\n\n".join(system_parts)
    if (t := oai.get("temperature")) is not None:
        out["temperature"] = t
    if (p := oai.get("top_p")) is not None:
        out["top_p"] = p
    if stop := oai.get("stop"):
        if isinstance(stop, str):
            out["stop_sequences"] = [stop]
        elif isinstance(stop, list) and all(isinstance(s, str) for s in stop):
            out["stop_sequences"] = stop
        else:
            return None, "stop must be a string or an array of strings"
    return out, None


def anthropic_to_oai(msg: dict) -> dict:
    """Anthropic message response -> OpenAI chat.completion response."""
    text = "".join(b.get("text", "") for b in msg.get("content") or []
                   if isinstance(b, dict) and b.get("type") == "text")
    return {
        "id": msg.get("id") or "chatcmpl-rotate",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": msg.get("model"),
        "choices": [{"index": 0,
                     "message": {"role": "assistant", "content": text},
                     "finish_reason": _FINISH.get(msg.get("stop_reason"), "stop")}],
        "usage": _oai_usage(msg.get("usage") or {}),
    }


class SseToOai:
    """Incremental Anthropic SSE -> OpenAI chunk translator.

    feed() takes decoded upstream text (any chunking, so lines may split anywhere)
    and returns whatever OpenAI `data:` lines are ready; tail() emits the final
    chunk, a usage chunk, and [DONE]. An upstream `error` event, or a stream that
    ends with no stop_reason, becomes an OpenAI error chunk and [DONE] instead.
    `usage` accumulates the Anthropic-style
    usage dict across message_start/message_delta for the caller's audit record.
    """

    def __init__(self):
        self._buf = ""
        self.id = "chatcmpl-rotate"
        self.model: str | None = None
        self.created = int(time.time())
        self.usage: dict = {}
        self.finish_reason: str | None = None
        self.errored = False
        # Upstream chunks are cut at arbitrary byte offsets, so a multi-byte
        # character can span two of them.
        self._dec = codecs.getincrementaldecoder("utf-8")(errors="replace")

    @staticmethod
    def _error_chunk(message: str, etype: str) -> str:
        # The openai client raises APIError on a chunk with an `error` key, so a
        # failure after the 200 status does not look like a finished answer.
        return "data: " + json.dumps(
            {"error": {"message": message, "type": etype}}) + "\n\n"

    def _chunk(self, delta: dict, finish: str | None = None) -> str:
        return "data: " + json.dumps({
            "id": self.id, "object": "chat.completion.chunk",
            "created": self.created, "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }) + "\n\n"

    def _absorb_usage(self, u: dict | None) -> None:
        for k, v in (u or {}).items():
            if isinstance(v, (int, float)):
                self.usage[k] = v

    def feed_bytes(self, chunk: bytes) -> str:
        return self.feed(self._dec.decode(chunk))

    def feed(self, text: str) -> str:
        self._buf += text
        out: list[str] = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            t = obj.get("type")
            if t == "message_start":
                m = obj.get("message") or {}
                self.id = m.get("id") or self.id
                self.model = m.get("model") or self.model
                self._absorb_usage(m.get("usage"))
                out.append(self._chunk({"role": "assistant", "content": ""}))
            elif t == "content_block_delta":
                d = obj.get("delta") or {}
                if d.get("type") == "text_delta" and d.get("text"):
                    out.append(self._chunk({"content": d["text"]}))
            elif t == "message_delta":
                d = obj.get("delta") or {}
                if d.get("stop_reason"):
                    self.finish_reason = _FINISH.get(d["stop_reason"], "stop")
                self._absorb_usage(obj.get("usage"))
            elif t == "error":
                e = obj.get("error") or {}
                self.errored = True
                out.append(self._error_chunk(
                    str(e.get("message") or "upstream stream error"),
                    str(e.get("type") or "api_error")))
        return "".join(out)

    def tail(self) -> str:
        # Flush the decoder first: bytes it held back may complete a final line.
        self.feed(self._dec.decode(b"", final=True))
        if self.errored:
            return "data: [DONE]\n\n"
        if self.finish_reason is None:
            # No stop_reason arrived: the stream was cut, so say so.
            return (self._error_chunk(
                "claude-rotate: upstream stream ended before message_stop",
                "api_error") + "data: [DONE]\n\n")
        usage_line = "data: " + json.dumps({
            "id": self.id, "object": "chat.completion.chunk",
            "created": self.created, "model": self.model,
            "choices": [], "usage": _oai_usage(self.usage),
        }) + "\n\n"
        return (self._chunk({}, self.finish_reason)
                + usage_line + "data: [DONE]\n\n")
