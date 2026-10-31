# Releasing jobwatch-native

The fast and slow timers run `~/apps/jobwatch-release`, a symlink to a built worktree of one commit; they never run
the editable checkout in `~/apps/jobwatch-native`, so editing that checkout cannot reach a live run.

Release: `deploy/release.sh <sha>` builds the commit under `~/projects/.worktrees/jobwatch-release-<shortsha>`,
checks that it imports, and swaps the symlink atomically. It prints the previous target. The next timer tick uses it;
nothing restarts by itself.

Undo: `ln -sfn <previous target> ~/apps/jobwatch-release` (the script prints the exact command).

Install the drop-ins in `systemd/` (`jobwatch-<unit>-release.conf`) as
`~/.config/systemd/user/<unit>.service.d/60-release-copy.conf` for `jobwatch-native-fast`, `jobwatch-native-slow`,
`jobwatch-native-web`, `jobwatch-agent` and `jobwatch-mcp-app`, then
`systemctl --user daemon-reload`. Timers pick up a release on their next run; the long-running servers (web, agent,
MCP app, connector) pick it up only when restarted.

The ChatGPT connector runs from the release copy too: install `systemd/jobwatch-connector-http.service` as
`~/.config/systemd/user/jobwatch-connector-http.service`, `daemon-reload`, then restart that one unit (it is a
long-running server, so it only picks up a new release on restart).

Old checkouts stay for as long as you keep them: `git -C ~/apps/jobwatch-native worktree remove ~/projects/.worktrees/jobwatch-release-<shortsha>`.
