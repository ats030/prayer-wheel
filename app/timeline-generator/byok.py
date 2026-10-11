"""Fixed Gemini experiment. No SDK, proxy, redirects, persistence or retries."""
import copy
import http.client
import json
import re
import threading
import time

PROVIDER = "google"
HOST = "generativelanguage.googleapis.com"
MODEL = "gemini-3.5-flash-lite"
PATH = "/v1beta/models/" + MODEL + ":generateContent"
# Tenths of USD millionths per token; ceil each call without float arithmetic.
INPUT_RATE, OUTPUT_RATE = 3, 25
# Reserve the full model output limit for thoughts in addition to visible output.
# minimal is an effort setting, not a hard guarantee of zero thought tokens.
THINKING_BOUND = 65536
MAX_RESPONSE = 512 * 1024


def token_cost(inputs, outputs):
    return (inputs * INPUT_RATE + outputs * OUTPUT_RATE + 9) // 10


class ByokError(Exception):
    """Fixed public code; deliberately not TimelineError (no local fallback)."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"AIza[A-Za-z0-9_-]{35}", key):
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
            "x-goog-api-key": key,
            "Content-Type": "application/json", "Accept-Encoding": "identity"})
        response = connection.getresponse()
        if response.status != 200:
            code = {400: "provider_request", 401: "invalid_api_key", 403: "provider_denied",
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
            return {"provider": PROVIDER, "model": MODEL, "calls": self.calls,
                    "input_tokens": self.input_tokens, "output_tokens": self.output_count,
                    "cost_microusd": self.cost, "cost_is_upper_bound": self.uncertain,
                    "max_cost_microusd": self.max_cost,
                    "cost_basis": "standard_paid_rate_estimate"}

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
                payload = json.dumps({
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {"maxOutputTokens": self.output_tokens,
                        "thinkingConfig": {"thinkingLevel": "minimal", "includeThoughts": False},
                        "responseMimeType": "application/json", "responseJsonSchema": closed_schema(schema)}},
                    ensure_ascii=False, allow_nan=False).encode()
                if len(payload) > self.input_bytes:
                    raise ByokError("input_budget")
                # UTF-8 bytes conservatively bound text tokens; reserve an extra
                # 8192 for provider framing/schema overhead. No tools or explicit cache.
                input_bound = len(payload) + 8192
                output_bound = self.output_tokens + THINKING_BOUND
                reservation = token_cost(input_bound, output_bound)
                if self.calls >= self.max_calls or self.cost + reservation > self.max_cost:
                    raise ByokError("cost_budget")
                self.calls += 1
                self.cost += reservation
                self.uncertain = True
                if self.on_usage is not None:
                    self.on_usage(self.summary())
                data = self.send(self._key, payload, min(120, left))
                usage = data.get("usageMetadata") if isinstance(data, dict) else None
                if (not isinstance(usage, dict) or any(type(usage.get(k)) is not int or usage[k] < 0
                        for k in ("promptTokenCount", "candidatesTokenCount", "totalTokenCount"))
                        or any(type(usage.get(k, 0)) is not int or usage.get(k, 0) < 0
                               for k in ("thoughtsTokenCount", "cachedContentTokenCount", "toolUsePromptTokenCount"))
                        or usage["promptTokenCount"] > input_bound
                        or usage["candidatesTokenCount"] > self.output_tokens
                        or usage.get("thoughtsTokenCount", 0) > THINKING_BOUND
                        or usage.get("cachedContentTokenCount", 0) > usage["promptTokenCount"]
                        or usage.get("toolUsePromptTokenCount", 0) != 0
                        or usage["totalTokenCount"] != usage["promptTokenCount"] + usage["candidatesTokenCount"] + usage.get("thoughtsTokenCount", 0)):
                    raise ByokError("provider_usage")
                charged_output = usage["candidatesTokenCount"] + usage.get("thoughtsTokenCount", 0)
                self.input_tokens += usage["promptTokenCount"]
                self.output_count += charged_output
                # Implicit cache discounts are deliberately ignored in the estimate.
                self.cost += token_cost(usage["promptTokenCount"], charged_output) - reservation
                self.uncertain = False
                if self.on_usage is not None:
                    self.on_usage(self.summary())
                if self.stopping.is_set():
                    raise ByokError("cancelled")
                candidates = data.get("candidates")
                if (not isinstance(candidates, list) or len(candidates) != 1
                        or not isinstance(candidates[0], dict) or candidates[0].get("finishReason") != "STOP"):
                    raise ByokError("provider_response")
                content = candidates[0].get("content", {}).get("parts")
                if (not isinstance(content, list) or not content
                        or any(not isinstance(part, dict) or not isinstance(part.get("text"), str)
                               or part.get("thought", False) is not False
                               or set(part) - {"text", "thought", "thoughtSignature"} for part in content)):
                    raise ByokError("provider_response")
                output = json.loads("".join(part["text"] for part in content))
                validate_output(output, schema)
                return output
            except Exception as exc:
                code = exc.code if isinstance(exc, ByokError) else "provider_response"
                self.failure, self._key = code, None
                raise ByokError(code) from None
