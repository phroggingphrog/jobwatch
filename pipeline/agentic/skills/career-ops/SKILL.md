---
name: career-ops
description: Use when inspecting a saved job, evaluating fit, or preparing an application.
---

# Career Ops

1. Inspect the full saved job ad and latest Jobwatch outcome with `career-reader`. Use `company_researcher` for the company/desired-skills brief and `market_evaluator` for existing model insights; load their relevant skills.
2. Use `assess_job` for evaluation only, or `prepare_application` (compatibility: `run_career_ops`) to prepare documents. Wait for the human approval prompt before paid model work or career-data changes. Load the relevant workflow skill before proceeding.
3. Use Jobwatch's returned run key, status, and reason as the outcome. Held or disabled means deferred, not completed. Conversation cannot override hard gates.
4. Ask the human when a personal fact is missing. Never guess or invent profile facts.
5. Never edit profile facts, change settings, submit an application, or contact anyone. The human alone presses final Submit outside this agent.
