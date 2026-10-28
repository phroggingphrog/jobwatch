"""OpenAI-compatible gateway client (OpenAI, OpenRouter, a local gateway, ...).

* The gateway is the server's (JOBWATCH_LLM_BASE_URL / JOBWATCH_LLM_API_KEY) unless the person saved their own
  base URL + key on the Models page (model_choice.py). Own gateways must be https (or loopback).
* Any model id the gateway accepts may be used; each person picks their own (model_choice.py).
* Keys are never logged or returned.
"""
from __future__ import annotations

import json
import math
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jobwatch.util import model_choice as model_choice
from jobwatch.settings import get as _setting

log = logging.getLogger(__name__)

BASE_URL = model_choice.SERVER_URL      # the server gateway; a person's own one is model_choice.gateway_url()
# Optional extra key sources (settings.env): a KEY=value file and the names to read from it, and a Pi models.json.
KEYS_ENV = Path(_setting("JOBWATCH_LLM_KEYS_FILE", "~/.config/jobwatch/keys.env"))
KEY_NAMES = [n.strip() for n in _setting("JOBWATCH_LLM_KEY_NAMES", "JOBWATCH_LLM_API_KEY").split(",") if n.strip()]
PI_MODELS = Path(_setting("JOBWATCH_LLM_PI_MODELS", "/nonexistent/pi-models.json"))

# $ per 1M tokens (input, output): API-equivalent prices of the model behind each combo
# (WHAT-HAPPENED 2026-10-05 13:13). Subscriptions, so this is an estimate, not money spent.
PRICES = {
    "claude/opus": (15.0, 75.0), "claude/sonnet": (2.0, 10.0),
    "claude/haiku": (1.0, 5.0), "openai/sol": (1.25, 10.0),
}


class LLMError(RuntimeError):
    pass


class DeadlineExceeded(LLMError):
    """The caller's monotonic budget is exhausted; do not retry."""


class SafeLLMError(LLMError):
    """Fixed classification for the counted single-attempt runtime API."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _price(model: str) -> tuple[float, float] | None:
    if model in PRICES:
        return PRICES[model]
    if model.startswith("claude/") and "sonnet" in model:
        return PRICES["claude/sonnet"]
    if model.startswith("claude/") and "opus" in model:
        return PRICES["claude/opus"]
    if model.startswith("claude/") and "haiku" in model:
        return PRICES["claude/haiku"]
    return None


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.expanduser().read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    except OSError:
        pass
    return out


def load_keys() -> list[str]:
    """Candidate API keys in order: JOBWATCH_LLM_API_KEY, the named keys in the keys file, then a Pi models.json key."""
    keys: list[str] = []
    own = model_choice.own_key()
    if own:                                              # the person's own gateway key: used alone
        return [own]
    if _setting("JOBWATCH_LLM_API_KEY"):
        keys.append(_setting("JOBWATCH_LLM_API_KEY"))
    file_keys = _read_env_file(KEYS_ENV)
    for name in KEY_NAMES:
        if file_keys.get(name) and file_keys[name] not in keys:
            keys.append(file_keys[name])
    try:
        pi = json.loads(PI_MODELS.expanduser().read_text())
        k2 = pi.get("providers", {}).get("omni", {}).get("apiKey")
        if k2 and k2 not in keys:
            keys.append(k2)
    except (OSError, ValueError):
        pass
    return keys


def _invoke_call(t: str) -> dict | None:
    """Claude sometimes answers in its native '<invoke name=..><parameter name=..>' form; read it as {tool, arguments}."""
    m = re.search(r'<invoke name="([^"]+)">(.*?)(?:</invoke>|$)', t, re.S)  # the closing tag is sometimes cut
    if not m:
        return None
    arguments: dict = {}
    for p in re.finditer(r'<parameter name="([^"]+)">(.*?)(?:</parameter>|(?=<parameter )|$)', m.group(2), re.S):
        value = p.group(2).strip()
        try:
            arguments[p.group(1)] = json.loads(value)
        except ValueError:
            arguments[p.group(1)] = value
    return {"tool": m.group(1), "arguments": arguments}


def parse_json(text: str) -> Any:
    """Parse a JSON object from model output (tolerates ``` fences, leading prose and Claude's native tool form)."""
    t = (text or "").strip()
    if t.startswith("<invoke") or t.startswith("<function_calls>"):
        call = _invoke_call(t)
        if call is not None:
            return call
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        start = t.find("{")
        if start >= 0:
            # The model sometimes follows its answer with a label and a second object ("Extra data"); only the first
            # complete object is the answer (the runtime runs one tool per reply anyway).
            try:
                return json.JSONDecoder().raw_decode(t[start:])[0]
            except ValueError:
                end = t.rfind("}")
                if end > start:
                    return json.loads(t[start:end + 1])
        raise


@dataclass
class LLMResult:
    model: str                 # requested (allowlisted) model id
    served: str | None         # model OmniRoute reports it answered with
    text: str
    data: Any = None
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    cost_usd: float | None = None


Transport = Callable[[str, dict, dict, float], tuple[int, dict]]


def _requests_transport(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, dict]:
    import requests
    with requests.Session() as session:
        session.trust_env = False                           # never send the prompt or the key through a proxy from the environment
        resp = session.post(url, headers=headers, json=body, timeout=timeout, allow_redirects=False)
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, {"error": {"message": resp.text[:300]}}


OVERLOAD_WAITS = (20, 45)
# model -> model to retry on when the gateway says overloaded; empty = no fallback.
OVERLOAD_FALLBACK: dict[str, str] = {}


def _rejected_options(status: int, payload: Any, body: dict) -> list[str]:
    """Optional request fields a 400 reply names as unsupported (never the required ones)."""
    if status != 400 or not isinstance(payload, dict):
        return []
    text = json.dumps(payload.get("error", ""), default=str).lower()
    return [option for option in ("response_format", "reasoning_effort") if option in body and option in text]


def _overloaded(status: int, payload: Any) -> bool:
    if status != 503 or not isinstance(payload, dict):
        return False
    err = payload.get("error")
    msg = str(err.get("message", "") if isinstance(err, dict) else err).lower()
    return "overloaded" in msg or "auth_unavailable" in msg


class LLM:
    def __init__(self, transport: Transport | None = None, keys: list[str] | None = None,
                 base_url: str | None = None):
        base_url = base_url or model_choice.gateway_url()
        if not model_choice.valid_url(base_url):
            raise ValueError("LLM base_url must be https (or a local gateway)")
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _requests_transport
        self._keys = keys
        self.calls: list[dict] = []    # model, served, usage, seconds, cost (no content)

    def _post(self, model: str, body: dict, headers: dict, timeout: float,
              deadline: float | None) -> tuple[int, dict]:
        """POST once; on an upstream overload 503 (bills nothing) wait 20 s, then 45 s, then
        switch to the fallback combo (owner 2026-10-13: "or use fallback")."""
        url = f"{self.base_url}/chat/completions"
        for wait in (*OVERLOAD_WAITS, None):
            remaining = deadline - time.monotonic() if deadline is not None else timeout
            status, payload = self.transport(url, headers, body, min(timeout, remaining))
            if not _overloaded(status, payload):
                return status, payload
            if wait is None or (deadline is not None and deadline - time.monotonic() <= wait + 30):
                break
            log.info("%s overloaded upstream; retrying in %ss", model, wait)
            time.sleep(wait)
        fallback = OVERLOAD_FALLBACK.get(model)
        if not fallback:
            return status, payload
        log.info("%s still overloaded; using fallback %s", model, fallback)
        remaining = deadline - time.monotonic() if deadline is not None else timeout
        return self.transport(url, headers, {**body, "model": fallback}, min(timeout, remaining))

    def chat_once(self, model: str, messages: list[dict], *, json_mode: bool = True,
                  max_tokens: int = 8000, temperature: float | None = None,
                  timeout: float = 60, deadline: float | None = None,
                  key_index: int = 0, reasoning_effort: str = "", tools: list | None = None,
                  send_response_format: bool = True, native_response: bool = False) -> LLMResult:
        """Make exactly one paid-route transport attempt using an explicit key.

        This method never loads key files or falls back to another credential. An upstream
        overload 503 (no tokens billed) is retried on the same key after a short wait. It is the
        only supported entry point for counted agentic runtime attempts.
        """
        model = (model or '').strip()
        keys = self._keys
        if keys is None or type(key_index) is not int or key_index < 0 or key_index >= len(keys):
            raise SafeLLMError("auth") from None
        if type(max_tokens) is not int or max_tokens < 1 or not isinstance(messages, list):
            raise SafeLLMError("invalid_response") from None
        try:
            json.dumps(messages, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise SafeLLMError("invalid_response") from None
        body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if temperature is not None: body["temperature"] = temperature
        # Native tool calling (`tools`): the model answers with a tool call instead of JSON text, so no response_format.
        if tools: body["tools"], body["tool_choice"] = tools, "auto"
        elif json_mode and send_response_format: body["response_format"] = {"type": "json_object"}
        if reasoning_effort: body["reasoning_effort"] = reasoning_effort
        remaining = deadline - time.monotonic() if deadline is not None else timeout
        if remaining <= 0: raise SafeLLMError("deadline") from None
        transport_failed = timed_out = False
        try:
            headers = {"Authorization": f"Bearer {keys[key_index]}", "Content-Type": "application/json"}
            if native_response:
                status, payload = self.transport(f'{self.base_url}/chat/completions', headers, body,
                                                 min(timeout, remaining))
            else:
                status, payload = self._post(model, body, headers, timeout, deadline)
            # A model behind the gateway may not know an optional OpenAI parameter (DeepSeek and reasoning_effort,
            # say). A 400 that names it is not billed: send the same request once without it. The reply is still
            # parsed as JSON, so the parameter only ever made the format stricter.
            for _ in range(0 if native_response else 2):  # native attempts never change protocol or route
                rejected = _rejected_options(status, payload, body)
                if not rejected:
                    break
                for option in rejected:
                    body.pop(option, None)
                log.info("%s rejected %s; retrying without", model, ",".join(rejected))
                status, payload = self._post(model, body, headers, timeout, deadline)
        except Exception as exc:
            transport_failed = True
            # A call cut off by the run's own clock is a deadline, not an outage (2026-10-18: 102 of 104
            # "model_unavailable" holds were the last job of a batch, the provider answering in 2-6 s otherwise).
            timed_out = 'timeout' in type(exc).__name__.lower() or (
                deadline is not None and time.monotonic() >= deadline - 1)
        if transport_failed:
            raise SafeLLMError("deadline" if timed_out else "unavailable") from None
        if deadline is not None and time.monotonic() >= deadline:
            raise SafeLLMError("deadline") from None
        err = payload.get("error") if isinstance(payload, dict) else None
        if status in (401, 403): raise SafeLLMError("auth") from None
        if status == 429: raise SafeLLMError("rate_limited") from None
        if status != 200 or err: raise SafeLLMError("transient") from None
        if isinstance(payload, dict) and isinstance(payload.get("choices"), list) and any(
                choice.get("finish_reason") in {"length", "max_tokens"}
                for choice in payload["choices"] if isinstance(choice, dict)):
            raise SafeLLMError("truncated_response") from None
        invalid_response = False
        detail = None
        try:
            message = payload["choices"][0]["message"]
            text = message["content"] or ""
            usage_raw = payload.get("usage")
            usage = {}
            if isinstance(usage_raw, dict):
                usage = {k: usage_raw.get(k) for k in ("prompt_tokens", "completion_tokens",
                    "total_tokens", "prompt_tokens_details", "completion_tokens_details",
                    "prompt_cache_hit_tokens", "prompt_cache_miss_tokens") if k in usage_raw}
            calls = message.get("tool_calls") if tools else None
            if native_response:
                data = message
            elif calls:
                # Same shape the JSON-per-step path returns. Only the first call is used: the runtime runs one
                # operation per reply, and the model asks again after seeing the result.
                function = calls[0]["function"]
                arguments = function.get("arguments")
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                data = {"tool": function["name"], "arguments": arguments}
            else:
                data = parse_json(text) if json_mode else None
        except Exception as exc:
            invalid_response = True
            detail = f"{type(exc).__name__}: {exc}\nraw payload: {json.dumps(payload, default=str)[:6000]}"
        if invalid_response:
            err_obj = SafeLLMError("invalid_response")
            err_obj.detail = detail  # logged to <data>/agentic-failures; never shown to callers
            raise err_obj from None
        result = LLMResult(model=model, served=None, text=text, data=data, usage=usage,
                           seconds=0.0, cost_usd=None)
        self.calls.append({"model": model, "served": None, "usage": usage, "seconds": 0.0, "cost_usd": None})
        return result

    def embed_once(self, model: str, texts: list[str], *, timeout: float = 30,
                   deadline: float | None = None) -> LLMResult:
        """One explicit-credential embedding attempt; no retry or provider fallback.

        The counted gateway adapter owns route approval and durable reservations.
        Errors never attach response bodies or candidate text.
        """
        if not self._keys:
            raise SafeLLMError('auth') from None
        if (not texts or len(texts) > 64 or any(type(t) is not str or not t or len(t) > 6000 for t in texts)
                or sum(len(t.encode('utf-8')) for t in texts) > 64_000):
            raise SafeLLMError('invalid_response') from None
        remaining = min(timeout, deadline - time.monotonic()) if deadline is not None else timeout
        if remaining <= 0:
            raise SafeLLMError('deadline') from None
        failed = False
        try:
            status, payload = self.transport(f'{self.base_url}/embeddings',
                {'Authorization': f'Bearer {self._keys[0]}', 'Content-Type': 'application/json'},
                {'model': model, 'input': texts, 'encoding_format': 'float'}, remaining)
        except Exception:
            failed = True
        if failed:
            raise SafeLLMError('unavailable') from None
        if deadline is not None and time.monotonic() >= deadline:
            raise SafeLLMError('deadline') from None
        if status in (401, 403):
            raise SafeLLMError('auth') from None
        if status == 429:
            raise SafeLLMError('rate_limited') from None
        if status != 200 or not isinstance(payload, dict) or payload.get('error'):
            raise SafeLLMError('unavailable') from None
        invalid = False
        try:
            rows = payload['data']
            if len(rows) != len(texts) or any(type(row['index']) is not int for row in rows):
                raise ValueError
            rows = sorted(rows, key=lambda row: row['index'])
            if [row['index'] for row in rows] != list(range(len(texts))):
                raise ValueError
            vectors = [row['embedding'] for row in rows]
            if (not vectors[0] or len(vectors[0]) > 16_384
                    or any(type(v) is not list or len(v) != len(vectors[0]) for v in vectors)
                    or any(type(x) not in (int, float) or not math.isfinite(x) for v in vectors for x in v)
                    or any(not any(x != 0 for x in v) for v in vectors)):
                raise ValueError
            prompt = payload.get('usage', {}).get('prompt_tokens')
            usage = {'prompt_tokens': prompt, 'completion_tokens': 0} if type(prompt) is int and prompt >= 0 else {}
        except Exception:
            invalid = True
        if invalid:
            raise SafeLLMError('invalid_response') from None
        return LLMResult(model=model, served=None, text='', data=vectors, usage=usage)

    def chat(self, model: str, messages: list[dict], *, json_mode: bool = True,
             max_tokens: int = 8000, temperature: float | None = None,
             timeout: float = 600, deadline: float | None = None) -> LLMResult:
        model = (model or '').strip()
        keys = self._keys if self._keys is not None else load_keys()
        if not keys:
            raise LLMError("no OmniRoute key available")
        body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        t0 = time.monotonic()
        last_err = "no attempt"
        for idx, key in enumerate(keys):
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            remaining = deadline - time.monotonic() if deadline is not None else timeout
            if remaining <= 0:
                raise DeadlineExceeded("model deadline exhausted")
            status, payload = self._post(model, body, headers, timeout, deadline)
            if deadline is not None and time.monotonic() >= deadline:
                raise DeadlineExceeded("model deadline exhausted")
            err = (payload or {}).get("error") if isinstance(payload, dict) else None
            if status in (401, 403) or (isinstance(err, dict) and str(err.get("code", "")) in
                                         ("permission_denied", "invalid_api_key")):
                last_err = f"key #{idx + 1} refused for {model} (HTTP {status})"
                log.info(last_err)
                continue
            if status != 200 or err:
                msg = (err or {}).get("message", "") if isinstance(err, dict) else str(err)
                raise LLMError(f"{model}: HTTP {status}: {str(msg)[:200]}")
            try:
                text = payload["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError(f"{model}: malformed response") from exc
            usage = payload.get("usage") or {}
            price = _price(model)
            cost = None
            if price and usage:
                cost = round(((usage.get("prompt_tokens") or 0) * price[0]
                              + (usage.get("completion_tokens") or 0) * price[1]) / 1e6, 5)
            res = LLMResult(model=model, served=payload.get("model"), text=text,
                            usage={k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")},
                            seconds=round(time.monotonic() - t0, 2), cost_usd=cost)
            if json_mode:
                try:
                    res.data = parse_json(text)
                except ValueError as exc:
                    raise LLMError(f"{model}: response was not valid JSON") from exc
            self.calls.append({"model": model, "served": res.served, "usage": res.usage,
                               "seconds": res.seconds, "cost_usd": cost})
            return res
        raise LLMError(f"{model}: every key was refused ({last_err})")
