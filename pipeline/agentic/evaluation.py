"""Offline tool-trajectory evaluation; no candidate text or model judge."""
from __future__ import annotations


def evaluate_tools(events, expected):
    from agentevals.trajectory.match import create_trajectory_match_evaluator
    from langsmith import tracing_context
    def messages(names):
        return [{'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': f'step-{i}', 'name': name, 'args': {}}]} for i, name in enumerate(names)]
    actual = [e['data']['tool'] for e in events if e['type'] == 'tool_started']
    evaluator = create_trajectory_match_evaluator(trajectory_match_mode='strict', tool_args_match_mode='ignore')
    with tracing_context(enabled=False):
        return evaluator(outputs={'messages': messages(actual)}, reference_outputs={'messages': messages(expected)})
