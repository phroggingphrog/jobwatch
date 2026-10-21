"""Tests for default-off agentic graph adapter and batch CLI."""
from __future__ import annotations

import sqlite3
import pytest

from pipeline.schemas import Stage
from pipeline.agentic.service import run_agentic_job, agentic_batch_run

def test_run_agentic_job_disabled_by_default(tmp_path):
    conn = sqlite3.connect(":memory:")
    config = {"agentic": {"enabled": False}}
    # When disabled, returns None or doesn't process
    result = run_agentic_job(posting_id=1, config=config, conn=conn)
    assert result is None

def test_agentic_batch_run_empty(tmp_path):
    conn = sqlite3.connect(":memory:")
    config = {"agentic": {"enabled": False}}
    summary = agentic_batch_run([], config, conn=conn)
    assert summary["processed"] == 0
