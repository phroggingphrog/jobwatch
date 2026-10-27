"""Notification channels: where Jobwatch tells a person that something failed, finished or needs them.

Built-in transports: none, ssh_append, command, webhook (see channels.py). More plug in through
`register_kind`. Docs: docs/notifications.md.
"""
from .channels import Channel, Receipt, register_kind, resolve_ref
from .events import (ACTION_REQUIRED, COMPLETION, FAILURE, ActionRequiredPayload, CompletionPayload, Event,
                     FailurePayload)
from .service import (ChannelConfig, DeliveryResult, add_channel, channels_for, deliver, digest_window,
                      disable_channel, dispatch, ensure, enqueue, test_channel)

__all__ = ["Channel", "Receipt", "register_kind", "resolve_ref", "Event", "FAILURE", "COMPLETION", "ACTION_REQUIRED",
           "FailurePayload", "CompletionPayload", "ActionRequiredPayload", "ChannelConfig", "DeliveryResult",
           "add_channel", "channels_for", "deliver", "digest_window", "disable_channel", "dispatch", "ensure",
           "enqueue", "test_channel"]
