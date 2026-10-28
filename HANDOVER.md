# Jobwatch handover

## Where things stand

- Source repository: `~/projects/jobwatch-public`, branch `codex/conversational-profile`.
- Chat onboarding guard verifies that quotes came from the person, values are grounded (affirmed span, same words, or the approved `Between jobs right now` → `Between roles` wording), and negation is not flipped.
- CV parsing saves the first profile version immediately; each answer/correction saves the next version with the person's exact words retained.
- Website/profile API review-and-confirm flow and other gated tools remain unchanged.
- No deployment performed. Undo: `git checkout 9dcced4 -- pipeline/agentic/chat.py tests/test_agentic_service.py` or drop the branch.

## Verification

- Focused onboarding selection: 4 passed.
- Verification B selection: 314 passed, 1 WeasyPrint HarfBuzz-Subset deprecation warning.
- No known verification failures remain. Deployment is the remaining operational step.
