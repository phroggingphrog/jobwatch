"""The only way a pipeline node talks to a model: ask, validate against a strict Pydantic schema, retry, give up.

attempts = MAX_ATTEMPTS (3). A reply that is not JSON, does not match the schema, or an HTTP / transport error each
use one attempt. On a retry the model is shown the validation error (the control flow does not change). After the
last attempt StructuredFailure is raised and the graph runner sends the job to the dead letter queue.
"""
from __future__ import annotations

import json
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from jobwatch.util.llm import DeadlineExceeded, LLM, parse_json

MAX_ATTEMPTS = 3
T = TypeVar("T", bound=BaseModel)


class StructuredFailure(RuntimeError):
    def __init__(self, node: str, attempts: int, errors: list[str]):
        self.node, self.attempts, self.errors = node, attempts, errors
        super().__init__(f"{node}: no valid reply after {attempts} attempts: {errors[-1] if errors else '?'}")


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), separators=(",", ":"))


def call(llm: LLM, model: str, system: str, user: str, schema: type[T], *, node: str,
         max_tokens: int = 4000, timeout: float = 180, deadline: float | None = None) -> tuple[T, int]:
    """(validated object, attempts used). Raises StructuredFailure after MAX_ATTEMPTS."""
    errors: list[str] = []
    base = [{"role": "system", "content": system + "\n\nReply with ONE JSON object that matches this JSON Schema "
                                                   "exactly (no extra keys, no markdown):\n" + schema_text(schema)},
            {"role": "user", "content": user}]
    for attempt in range(1, MAX_ATTEMPTS + 1):
        if deadline is not None and time.monotonic() >= deadline:
            raise DeadlineExceeded(f"{node}: deadline exhausted")
        messages = list(base)
        if errors:
            messages.append({"role": "user", "content": "Your previous reply was rejected by the validator: "
                                                        f"{errors[-1][:800]}\nReply again with ONE valid JSON object."})
        try:
            # strict json_mode fails on some OmniRoute routes; the reply is parsed and validated here instead
            budget = {} if deadline is None else {"deadline": deadline}
            res = llm.chat(model, messages, json_mode=False, max_tokens=max_tokens,
                           timeout=min(timeout, deadline - time.monotonic()) if deadline is not None else timeout,
                           **budget)
            if deadline is not None and time.monotonic() >= deadline:
                raise DeadlineExceeded(f"{node}: deadline exhausted")
            data = parse_json(res.text or "")
            return schema.model_validate(data), attempt
        except DeadlineExceeded:
            raise
        except ValidationError as exc:
            errors.append("schema: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
                                                 for e in exc.errors()[:8]))
        except ValueError as exc:                       # not JSON at all
            errors.append(f"json: {str(exc)[:200]}")
        except Exception as exc:                        # noqa: BLE001 - HTTP, timeout, refused key: one attempt each
            errors.append(f"call: {type(exc).__name__}: {str(exc)[:200]}")
    if deadline is not None and time.monotonic() >= deadline:
        raise DeadlineExceeded(f"{node}: deadline exhausted")
    raise StructuredFailure(node, MAX_ATTEMPTS, errors)
