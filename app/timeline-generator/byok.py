"""Fixed Anthropic experiment. No SDK, proxy, redirects, persistence or retries."""
import copy
import http.client
import json
import re
import threading
import time

HOST = "api.anthropic.com"
PATH = "/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
# USD millionths per token, standard uncached text rates reviewed 2026-10-11.
INPUT_RATE, OUTPUT_RATE = 1, 5
MAX_RESPONSE = 512 * 1024


class ByokError(Exception):
    """Fixed public code; deliberately not TimelineError (no local fallback)."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"sk-ant-[A-Za-z0-9_-]{20,300}", key):
        raise ByokError("invalid_api_key")


def closed_schema(schema):
    result = copy.deepcopy(schema)
    def close(node):
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            node["additionalProperties"] = False
        for value in node.values():
            if isinstance(value, dict):
                close(value)
            elif isinstance(value, list):
                for item in value:
                    close(item)
    close(result)
    return result


def validate_output(value, schema):
    kind = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind not in types or type(value) is not types[kind] or ("enum" in schema and value not in schema["enum"]):
        raise ByokError("provider_response")
    if kind == "object":
        properties = schema.get("properties", {})
        if set(schema.get("required", [])) - value.keys() or value.keys() - properties.keys():
            raise ByokError("provider_response")
        for name, item in value.items():
            validate_output(item, properties[name])
    elif kind == "array":
        for item in value:
            validate_output(item, schema["items"])


def transport(key, payload, timeout):
    # Certificate-verified TLS to one literal provider; no environment proxy,
    # URL input, redirects, SDK retry or exception body passed to the caller.
    connection = http.client.HTTPSConnection(HOST, timeout=timeout)
    try:
        connection.request("POST", PATH, body=payload, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01",
            "Content-Type": "application/json", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status != 200:
            code = {401: "invalid_api_key", 403: "provider_denied",
                    429: "provider_rate"}.get(response.status, "provider_unavailable")
            raise ByokError(code)
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ByokError("provider_response")
        return json.loads(body)
    except ByokError:
        raise
    except Exception:
        raise ByokError("provider_unavailable") from None
    finally:
        connection.close()


class ModelSession:
    def __init__(self, key, stopping, *, max_cost_microusd, max_calls,
                 input_bytes, output_tokens, send=transport, on_usage=None):
        validate_key(key)
        values = (max_cost_microusd, max_calls, input_bytes, output_tokens)
        if (any(type(v) is not int or v <= 0 for v in values)
                or max_cost_microusd > 5_000_000 or max_calls > 100
                or input_bytes > 160_000 or output_tokens > 8192):
            raise ValueError("Explicit bounded model limits required")
        self._key, self.stopping, self.send = key, stopping, send
        self.on_usage = on_usage
        self.max_cost, self.max_calls = max_cost_microusd, max_calls
        self.input_bytes, self.output_tokens = input_bytes, output_tokens
        self.lock = threading.RLock()
        self.calls = self.input_tokens = self.output_count = self.cost = 0
        self.uncertain = False
        self.failure = None

    def close(self):
        with self.lock:
            self._key = None

    def summary(self):
        with self.lock:
            return {"provider": "anthropic", "model": MODEL, "calls": self.calls,
                    "input_tokens": self.input_tokens, "output_tokens": self.output_count,
                    "cost_microusd": self.cost, "cost_is_upper_bound": self.uncertain,
                    "max_cost_microusd": self.max_cost}

    def __call__(self, system, prompt, deadline, schema):
        # Serialize generation and verification. A failed call latches the job,
        # including prefetch workers, so no later stage can spend again.
        with self.lock:
            try:
                if self.stopping.is_set():
                    raise ByokError("cancelled")
                if self.failure:
                    raise ByokError(self.failure)
                if self._key is None:
                    raise ByokError("key_gone")
                left = deadline - time.monotonic()
                if left < 5:
                    raise ByokError("time_limit")
                payload = json.dumps({"model": MODEL, "max_tokens": self.output_tokens,
                    "temperature": 0, "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                    "output_config": {"format": {"type": "json_schema", "schema": closed_schema(schema)}}},
                    ensure_ascii=False, allow_nan=False).encode()
                if len(payload) > self.input_bytes:
                    raise ByokError("input_budget")
                # UTF-8 bytes conservatively bound text tokens; reserve an extra
                # 8192 for provider framing/schema overhead. No cache/tools/think.
                input_bound = len(payload) + 8192
                reservation = input_bound * INPUT_RATE + self.output_tokens * OUTPUT_RATE
                if self.calls >= self.max_calls or self.cost + reservation > self.max_cost:
                    raise ByokError("cost_budget")
                self.calls += 1
                self.cost += reservation
                self.uncertain = True
                if self.on_usage is not None:
                    self.on_usage(self.summary())
                data = self.send(self._key, payload, min(120, left))
                usage = data.get("usage") if isinstance(data, dict) else None
                if (not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                        for k in ("input_tokens", "output_tokens"))
                        or usage["input_tokens"] > input_bound or usage["output_tokens"] > self.output_tokens
                        or usage.get("cache_creation_input_tokens", 0) != 0
                        or usage.get("cache_read_input_tokens", 0) != 0):
                    raise ByokError("provider_usage")
                self.input_tokens += usage["input_tokens"]
                self.output_count += usage["output_tokens"]
                self.cost += usage["input_tokens"] * INPUT_RATE + usage["output_tokens"] * OUTPUT_RATE - reservation
                self.uncertain = False
                if self.on_usage is not None:
                    self.on_usage(self.summary())
                if self.stopping.is_set():
                    raise ByokError("cancelled")
                if data.get("stop_reason") != "end_turn":
                    raise ByokError("provider_response")
                content = data.get("content")
                if (not isinstance(content, list) or len(content) != 1
                        or not isinstance(content[0], dict) or content[0].get("type") != "text"):
                    raise ByokError("provider_response")
                output = json.loads(content[0]["text"])
                validate_output(output, schema)
                return output
            except Exception as exc:
                code = exc.code if isinstance(exc, ByokError) else "provider_response"
                self.failure, self._key = code, None
                raise ByokError(code) from None
