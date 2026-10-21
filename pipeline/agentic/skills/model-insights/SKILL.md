---
name: model-insights
description: Use when explaining occupation fits, Bayesian preference readiness, learned job-choice comparisons or historical callback rates.
---

Delegate to market_evaluator. Use existing tool calculations, not arithmetic invented in the chat.

- candidate_paths: structural occupational activity coverage and cosine similarity, with source/version provenance. This is not a qualification or hiring probability; suggested mappings stay unverified.
- preference_insights: local R/JAGS conditional-logit readiness. Predictions require a valid current owner fit and an already answered current comparison. Never preview predictions before the owner labels a choice. Never invent training labels or treat learned preferences as personal facts.
- callback_insights: historical Beta-Binomial callback rates with a Beta(1,15) prior and 95% interval. Prior-only is not observed success; these are not individual-job hiring odds.
- application_status: authoritative saved job evaluation and eligibility outcome.

Report insufficient data, stale/rejected fits and missing dependencies explicitly. Fitting and choice recording remain on the existing owner-controlled CLI/web paths; these tools only read. The legacy pipeline's weighted rubric is a separate execution mode; it is not secretly blended into agentic scores. No live market-demand or salary comparison is implied.
