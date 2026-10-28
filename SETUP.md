# Set up your own Jobwatch

Jobwatch is for a few people on one server. Everyone gets their own folder, profile, CV, answers, job list and logins.
Nothing is shared between people and nothing is ever submitted for you.

1. `uv sync`, copy `.env.example` to `.env`, fill it in (see below), then `uv run jobwatch web`.
2. Open the board, sign in as the first person (password from `JOBWATCH_OWNER_PASSWORD`). Friends sign up with `JOBWATCH_INVITE_CODE`.
3. First sign-in opens "Welcome": upload your CV. Jobwatch builds your profile, your job-search keywords (for your field, not anyone else's) and then asks the rest as question cards.
4. Connect accounts (Seek, LinkedIn, Indeed): log in once in the browser window Jobwatch opens. Each person has their own browser folder.
5. Connect Google (optional): see below.

## Model key
Jobwatch calls models through one OpenAI-compatible gateway (`JOBWATCH_LLM_BASE_URL`, `JOBWATCH_LLM_API_KEY`). Use paid routes only: your CV and answers are sent there.

## Google (Gmail and Drive)
Gmail access lets Jobwatch read your job mail, write follow-up drafts and archive/trash job mail. It never sends: you press Send yourself.
1. console.cloud.google.com: new project, enable Gmail API and Google Drive API.
2. OAuth consent screen: External, status Testing. Add every person who will use it under Test users.
3. Credentials: OAuth client ID, type Web application. Authorized redirect URI = `GOOGLE_REDIRECT_URI`.
4. Put the client ID and secret in `.env`, or in `google.env` beside `settings.env` (Jobwatch reads both). Each person then clicks "Connect Google" on the Connect page.
(Testing-mode tokens expire after 7 days; reconnect, or publish the app for yourself.)

## Before you publish the code
Do not publish this repo's history: the `.planning/`, STATUS and TRACK files mention the original owner's server paths. Export a clean copy (`git archive`) and check `git grep -iE "yourname|/home/"` is empty. `.env`, `users.json`, `google.json` and the data folder must never be committed.
