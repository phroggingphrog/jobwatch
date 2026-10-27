"""The one place that knows the older install-wide settings and stored codes from before channels existed.

Settings: two names in the settings file or environment name an ssh host and a remote file. When both are set
the owner's person gets an equivalent `ssh_append` channel at runtime (see service.channels_for), so an existing
install keeps working with no configuration step. Stored codes: incident rows written before the generic
vocabulary keep their old values; `present_state` reads them as the generic ones.
"""
from __future__ import annotations

SSH_ENV = "JOBWATCH_HERMES_SSH"
FILE_ENV = "JOBWATCH_HERMES_FILE"
ENV_NAMES = (SSH_ENV, FILE_ENV)
ALIAS_CHANNEL = "legacy-env"

_STATE = {"handed_off": "delivered", "sending": "pending"}
_ERROR = {"hermes_handoff_failed": "delivery_failed", "hermes_not_configured": "no_channel"}


def present_state(state: str | None, error: str | None) -> tuple[str | None, str | None]:
    """(state, error) as stored -> generic wording: delivered / pending / failed / no_channel."""
    state, error = _STATE.get(state, state), _ERROR.get(error, error)
    if state == "failed" and error == "no_channel":
        return "no_channel", None
    return state, error
