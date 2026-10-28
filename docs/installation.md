# Installation and settings

[Project overview](../README.md) · [Current intent](../INTENT.md)

Reference material moved from README; commands describe available source interfaces,
not proof of current service activation or end-to-end acceptance.

## Available capabilities

- Native agent API: persistent conversations/runs, progress streaming, scoped human approvals and protected documents; see [backend setup](../pipeline/agentic/CHAT.md).
- Collectors for job boards, company career pages (many ATS systems), RSS and Reddit; duplicates removed; SQLite storage.
- Web board (FastAPI + HTMX): Board, Table, Job, Applications, Inbox (mail outcomes), Sources, Insights.
- Profile built from your CV; evidence-backed drafts with a fresh-context reviewer and a code verifier.
- Several people per install, each with their own folder, profile, answers and logins.
- Optional Google (Gmail/Drive) connection for follow-up drafts and outcome tracking. Nothing is ever sent for you.
- Optional push of urgent messages to a personal assistant over ssh.

Candidate data is stored locally, but job sources, approved model providers and
explicitly connected integrations can receive data as their operations require.

## Install

```bash
git clone <this repo> ~/apps/jobwatch && cd ~/apps/jobwatch
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev]'
mkdir -p ~/.config/jobwatch && cp .env.example ~/.config/jobwatch/settings.env   # then edit it
.venv/bin/jobwatch init-db
.venv/bin/jobwatch web                      # http://127.0.0.1:8960
```

Systemd user units (fast/slow collection, outcomes, digest, web) are in `systemd/`; copy them to
`~/.config/systemd/user/` only when configuring an authorized deployment.
The initial commands above do not activate collection timers. See
[SETUP.md](../SETUP.md) for first sign-in and connecting accounts, and
[operations](operations.md) for timer setup.
For a first run on a new server, [docs/service-bring-up.md](../docs/service-bring-up.md) puts these steps in
order with a check at each one, before any unit is enabled at boot.

## Settings (`~/.config/jobwatch/settings.env`)

`KEY=value` lines; a real environment variable of the same name wins. Use another file with `JOBWATCH_SETTINGS`.

| Key | Meaning | Default |
|---|---|---|
| `JOBWATCH_DATA_DIR` | Profiles, ledger, drafts (one folder per person) | `~/.local/share/jobwatch` |
| `JOBWATCH_DB` | SQLite file | `<jobwatch.yaml db_path>` = `~/.local/share/jobwatch/jobwatch.db` |
| `JOBWATCH_PROFILE_DIR` | Profile folder override | `<data dir>/profile` |
| `JOBWATCH_CAREER_DIR` | Career record folder | `<data dir>/career` |
| `JOBWATCH_LLM_BASE_URL` | OpenAI-compatible gateway URL | `https://api.openai.com/v1` |
| `JOBWATCH_LLM_API_KEY` | Gateway API key | none |
| `JOBWATCH_LLM_KEYS_FILE` | Optional `KEY=value` file holding more keys | `~/.config/jobwatch/keys.env` |
| `JOBWATCH_LLM_KEY_NAMES` | Names (comma list) to read from that file | `JOBWATCH_LLM_API_KEY` |
| `JOBWATCH_LLM_MODEL` | Default model id for every role (each person can pick their own on the Models page) | `gpt-4o` |
| `JOBWATCH_PUBLIC_HOST`, `JOBWATCH_BOARD_URL` | Address you open the board at | localhost:8960 |
| `JOBWATCH_NOTIFY_CMD` | Command run to notify you | none |
| notification channels | Where urgent messages go (ssh append, local command, webhook): `jobwatch notify channels add ...`, see [docs/notifications.md](../docs/notifications.md) | none (messages stay in the Chat page) |
| `JOBWATCH_SESSION_SECRET`, `JOBWATCH_INVITE_CODE`, `JOBWATCH_OWNER_PASSWORD` | Sign-in | sign-in off |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Your own Google OAuth client | Google off |

Bring your own keys: create an API key with any OpenAI-compatible provider, and (for Google) your own OAuth client in
Google Cloud Console (Gmail API + Drive API, Web application; redirect URI = `GOOGLE_REDIRECT_URI`). Your CV and answers
are sent to the model gateway you choose, so pick a provider you trust.

## Credits

Jobwatch borrows ideas from [career-ops](https://github.com/santifer/career-ops) by santifer (MIT); the copied
anti-slop file and the career-ops templates keep that project's license notice. Resume-Matcher, Reactive Resume and
jobsync were inspirations.
