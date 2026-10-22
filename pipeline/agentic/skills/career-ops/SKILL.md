---
name: career-ops
description: Use when inspecting a saved job, evaluating fit, or preparing an application.
---

# Career Ops

1. Inspect the full saved job ad and latest Jobwatch outcome with `career-reader`. Use `company_researcher` for the company/desired-skills brief and `market_evaluator` for existing model insights; load their relevant skills.
2. Use `assess_job` for evaluation only. Read `ranked_shortlist` after assessment; `prepare_application` (compatibility: `run_career_ops`) selects one current eligible entry, or `select_jobs` selects 1–10 entries with their exact entry IDs and run keys. Human approval authorizes preparation only. The durable selection may be pending dispatch with a null run ID; use `selection_status` and the native run/artifact endpoints for the eventual package. Load the relevant workflow skill before proceeding.
3. Use Jobwatch's returned run key, status, and reason as the outcome. Held or disabled means deferred, not completed. Conversation cannot override hard gates.
4. Ask the human when a personal fact is missing. Never guess or invent profile facts.
5. Never edit profile facts, change settings, or contact anyone. Submit only when the owner asks to submit a specific job: call `submit_application` (it needs their approval of that exact reviewed form and only queues the press), then report `submit_status`.
6. `feedback_history`, `exclusion_rules` and `next_feedback_prompt` expose current person-bound state. `reject_posting` hides only its current entry; `restore_posting` names the original rejection and rechecks eligibility. Propose and confirm exclusion amendments separately with `propose_exclusion` and `confirm_exclusion`; only the exact digest approval changes policy and it stales dependent assessments.
7. `pick_comparison`, `answer_question`, `dismiss_prompt` and `cancel_selection` require exact-payload human approval. Copy question answers verbatim from the person's words; never generate a choice, answer or approval for them. Answers stay feedback until the existing profile-confirmation workflow approves them. Displays, rejections, restorations and selections never become preference training choices.
