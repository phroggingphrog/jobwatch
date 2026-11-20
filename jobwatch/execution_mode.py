"""Resolve one effective AI mode: off, screened or agentic.

`reader` and `pipeline` are retired: they are still accepted (so an older configuration keeps chat and the API
available), but collection no longer dispatches any assessment under them."""
from __future__ import annotations

MODES = ('off', 'reader', 'pipeline', 'agentic', 'screened')
RETIRED_MODES = ('reader', 'pipeline')


def effective_mode(config) -> str:
    root = config.settings if hasattr(config, 'settings') else (config or {})
    pipeline = root.get('pipeline', root)
    mode = pipeline.get('execution_mode')
    if mode is not None:
        if mode not in MODES:
            raise ValueError('invalid_execution_mode')
        return mode
    # Preserve the old precedence. An explicit mode supersedes both old flags.
    # Screened replaced standalone agentic as the main path (owner 2026-10-31); agentic now runs on promoted jobs.
    if pipeline.get('agentic', {}).get('enabled') is True:
        return 'screened'
    return 'pipeline' if pipeline.get('enabled') is True else 'reader'
