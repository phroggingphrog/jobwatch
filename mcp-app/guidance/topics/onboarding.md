1. {{tool:onboarding_status}}: status is not_started, parsing, draft or confirmed.
2. not_started: the person's documents must already be uploaded in Jobwatch; {{tool:start_onboarding}} takes their upload_ids. Ask the person if you do not have them.
3. draft: ask the person the saved questions in your own conversation. Save answers with {{tool:answer_onboarding_question}} or edits with {{tool:update_onboarding}}, always with the current expected_revision. Save only what the person said. Never invent facts.
4. {{tool:review_onboarding}}: show the exact facts, search scope (basis, locations, daily assessments, token allowance) and limits.
5. Only after the person clearly agrees to that exact review, call {{tool:confirm_onboarding}} with the unchanged proposal_digest and scope_digest. Confirming authorises discovery and assessment only; no documents, messages or submissions.
