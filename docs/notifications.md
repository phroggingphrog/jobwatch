# Notifications

Jobwatch tells a person when something failed, finished or needs them. Where that message goes is a **channel**:
a small stored config, one or more per person. Nothing is hard-wired to one assistant or service. With no channel,
messages only appear on the Chat page.

## Events

| Event | Meaning | Sent by default |
|---|---|---|
| `failure` | a job or run stopped because jobwatch failed (not a normal decision) | yes |
| `action_required` | the person has to do something | yes |
| `completion` | something finished (for example a job is ready) | no, Chat page only |

Each event carries a one-line text, a dedupe key and a typed payload of fixed codes and numbers (never advertisement
text, profile data or exception text). A channel can filter which event kinds it takes.

## Channel kinds

| Kind | What it does | Config keys |
|---|---|---|
| `none` | does nothing (a placeholder, the default) | none |
| `ssh_append` | `ssh host 'cat >> file'`: appends the line to a file on another machine | `host` or `host_ref`, `file` or `file_ref` |
| `command` | runs a local command with the message on stdin; no shell, the argv list is run as given | `argv` (a list) |
| `webhook` | POSTs the event as JSON | `url_ref` |

`ssh_append` uses `ssh -o BatchMode=yes`, so the key must already work without a password.

## Add, test, turn off

Run as one person with `jobwatch --user NAME ...` (no `--user` = the default person).

```
jobwatch notify channels add phone --kind webhook --set url_ref=env:MY_WEBHOOK_URL
jobwatch notify channels add inbox --kind ssh_append --set host=me@my-server --set file='~/jobwatch-notify.txt'
jobwatch notify channels add bell  --kind command --config-json '{"argv": ["notify-send", "Jobwatch"]}'
jobwatch notify channels list
jobwatch notify channels test phone      # sends a harmless test event, prints the receipt
jobwatch notify channels disable phone
```

`add` with an existing name replaces that channel. Options: `--events failure,completion,action_required`,
`--digest incident=21600` (see below).

## Secrets

A config never holds a secret. Anything secret is a **reference**, a key ending in `_ref`:

* `env:NAME`: the setting or environment variable `NAME` (`~/.config/jobwatch/settings.env` is read too)
* `file:/path`: the first line of a file (keep it readable only by you)

`add` refuses a literal credential (a key such as `token`, `password`, a URL with a password in it, or a `webhook`
`url`). Receipts, logs and the `test` output only contain short codes (`ok`, `timeout`, `exit_255`, `http_502`,
`not_configured`); never the address, URL, token or message.

## Delivery

* **Outbox** (`notify_outbox`): an alert is queued once per channel and sent; a failure is retried after 1, 5, 15
  and then 60 minutes, up to 8 attempts. A retry runs on the next alert or `python -m jobwatch.notify --flush`.
* **Dedupe**: the same key is sent once a day per channel (`alert()` keys by failure kind).
* **Digest**: failures of assessment jobs are batched into one message per window (default 6 hours) by a channel's
  `digest` policy, `{"incident": seconds}`; the shortest window among the channels that take them wins, `0`
  sends each at once. The digest keeps its own pending/retry state on each incident, so a failed delivery leaves
  every incident pending.
* **Receipts** (`notify_receipts`): one row per attempt: channel, attempt number, `delivered` or `failed`, a short code.

Incident rows show the delivery as `delivered`, `pending`, `failed` or `no_channel` on the web page, in the API and in
the MCP app. Rows written by earlier versions (stored as `handed_off`) read as `delivered`.

Tables: `notify_channels`, `notify_outbox`, `notify_receipts` (database migration 17; `jobwatch.notifier.ensure()`
creates them in a database that has not been migrated).

## Older install-wide settings (alias)

Before channels existed, two settings pushed urgent messages over ssh: `JOBWATCH_HERMES_SSH` (`user@host`) and
`JOBWATCH_HERMES_FILE` (the remote file). They still work. While both are set, the **default person** (the owner)
gets an equivalent `ssh_append` channel named `legacy-env` at runtime, nothing is stored and nothing needs
configuring. The alias steps aside as soon as that person has a channel of their own that can deliver, and
`jobwatch notify channels disable legacy-env` turns it off. Other accounts never use it. Only
`jobwatch/notifier/legacy.py` knows these names.

## Adding another transport (design: a chat-bot service such as Telegram)

A transport is a class with `kind`, `send(event) -> Receipt` and `healthy() -> bool`, registered once:

```python
from jobwatch.notifier import register_kind
register_kind("telegram", TelegramChannel, allowed_keys={"chat_id", "bot_token_ref"})
```

Nothing else changes: configs, filters, dedupe, digest, retry, receipts and the CLI come with the interface. Design
notes for a Telegram transport (not built; no bot exists and none is connected):

* the bot token is a `_ref` (`bot_token_ref=file:/path`); the linked chat id is per-person config
* linking a person's chat is an authenticated step in the web app that stores `chat_id` for that person, and
  revoking is `disable` plus deleting the row; one person's channel never carries another person's events
* `send()` maps the event to one message; `Receipt.detail` is a code such as `http_429`
* optional interactive buttons would call authenticated, typed Jobwatch APIs; this layer only sends

## Other places the code names a channel

`JOBWATCH_NOTIFY_CMD` (README) is the separate, older command the profile-question cards use; it is not part of this layer.
