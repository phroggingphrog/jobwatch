"""Prescreen: cheap, deterministic checks that run BEFORE any model.

One generic engine (engine.py) reads its vocabulary and rules from database tables (prescreen_terms, prescreen_rules,
prescreen_overrides) and writes an audit row per decision (prescreen_decisions). The code holds no words, no field of work
and no person. A match is a reversible skip with a visible reason, never a recommendation. See docs/prescreen.md.
"""
