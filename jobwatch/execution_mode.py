"""Resolve one effective AI mode, preserving legacy installs until migrated."""
from __future__ import annotations


def effective_mode(config) -> str:
    root = config.settings if hasattr(config, 'settings') else (config or {})
    pipeline = root.get('pipeline', root)
    mode = pipeline.get('execution_mode')
    if mode is not None:
        if mode not in ('off', 'reader', 'pipeline', 'agentic'):
            raise ValueError('invalid_execution_mode')
        return mode
    # Preserve the old precedence. An explicit mode supersedes both old flags.
    if pipeline.get('agentic', {}).get('enabled') is True:
        return 'agentic'
    return 'pipeline' if pipeline.get('enabled') is True else 'reader'
