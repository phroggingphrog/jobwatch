<!-- phrog-development:start -->
For development, read `/home/phroggingphrog/.dsh/profiles/vanilla/node_modules/phrog-development/skills/using-phrog-development/SKILL.md`
and `/home/phroggingphrog/.agents/AGENTS.md`. Use automatic upstream OpenSpec routing for substantial changes; small fixes and questions need no new spec or setup.
Reuse existing authorization and the current project workspace before creating isolation. New worktrees belong under `~/projects/.worktrees/` through the host's workspace tools; a worktree never authorizes another deployment.
Shared server workflow controls older workflow text below; retain repository product, security and contribution requirements. Backlog owns overall server work status; private GitHub repositories retain their issue tracking without duplicate tickets. Verify the owner's actual deployment before claiming live or fixed.
<!-- phrog-development:end -->

> Retained Jobwatch checkout. Current served source is `~/apps/jobwatch-native`; use `~/projects/jobwatch/AGENTS.md` for the current map. This folder is not a release target merely because it exists.

# Jobwatch: rules for any agent
- Read INTENT.md and GOAL_CONTRACT.md first; owner words are the spec.
- Follow the current shared verification policy: focused checks, at most three check/fix rounds, and exact owner-facing deployment proof before a live claim.
- Quality gates (reviewer, fact check, letter rules) block only on checkable facts: true, right company, no placeholders. Taste (voice, tailoring) gives notes for one rewrite and never blocks. Same rejection twice: fix the conflicting rules, never add a banned phrase (owner 2026-10-20).
- Before every release run `jobwatch check --code`: it lists any place where the person's own facts (from their profile) appear in code; they belong in profile.yaml / interests_and_criteria.yaml / settings.env (owner 2026-10-20: "what can be prevented in the future").
