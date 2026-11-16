"""Resolve one effective AI mode: off, screened or agentic.

The retired `reader` and `pipeline` modes resolve to `off`, so an older configuration never dispatches paid work."""
from __future__ import annotations

MODES = ('off', 'agentic', 'screened')
RETIRED_MODES = ('reader', 'pipeline')


def effective_mode(config) -> str:
    root = config.settings if hasattr(config, 'settings') else (config or {})
    pipeline = root.get('pipeline', root)
    mode = pipeline.get('execution_mode')
    if mode is not None:
        if mode in RETIRED_MODES:
            return 'off'
        if mode not in MODES:
            raise ValueError('invalid_execution_mode')
        return mode
    # An explicit mode supersedes the old flag. Screened is the main path (owner 2026-10-31); agentic runs on promoted jobs.
    if pipeline.get('agentic', {}).get('enabled') is True:
        return 'screened'
    return 'off'
