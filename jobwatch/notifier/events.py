"""What can be notified: three event types with typed payloads. A payload holds fixed codes and numbers, never
advertisement text, profile data or exception text."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FAILURE, COMPLETION, ACTION_REQUIRED = "failure", "completion", "action_required"
EVENT_KINDS = (FAILURE, COMPLETION, ACTION_REQUIRED)
DAY = 86400


@dataclass(frozen=True)
class FailurePayload:
    reason: str
    phase: str | None = None
    posting_id: int | None = None
    run_id: str | None = None
    count: int = 1


@dataclass(frozen=True)
class CompletionPayload:
    posting_id: int | None = None
    title: str = ""
    company: str = ""
    url: str = ""


@dataclass(frozen=True)
class ActionRequiredPayload:
    action: str
    posting_id: int | None = None
    url: str = ""


PAYLOADS = {FAILURE: FailurePayload, COMPLETION: CompletionPayload, ACTION_REQUIRED: ActionRequiredPayload}


@dataclass(frozen=True)
class Event:
    kind: str
    text: str                       # the finished one-line message every transport sends
    key: str                        # dedupe key: the same key inside `dedupe_window` seconds is sent once
    payload: Any = None             # FailurePayload | CompletionPayload | ActionRequiredPayload
    group: str | None = None        # events with a group are batched by the channel's digest window (e.g. "incident")
    dedupe_window: int = DAY
    extra: dict = field(default_factory=dict, compare=False)

    def __post_init__(self):
        if self.kind not in EVENT_KINDS:
            raise ValueError("invalid_event_kind")
        if self.payload is not None and not isinstance(self.payload, PAYLOADS[self.kind]):
            raise ValueError("payload_does_not_match_event_kind")
        if not self.key:
            raise ValueError("event_key_required")

    @property
    def line(self) -> str:
        return " ".join(self.text.split())

    def to_dict(self) -> dict:
        return {"kind": self.kind, "text": self.text, "key": self.key, "group": self.group,
                "dedupe_window": self.dedupe_window,
                "payload": asdict(self.payload) if self.payload is not None else None}

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        payload = data.get("payload")
        return cls(data["kind"], data["text"], data["key"],
                   PAYLOADS[data["kind"]](**payload) if payload is not None else None,
                   data.get("group"), int(data.get("dedupe_window", DAY)))
