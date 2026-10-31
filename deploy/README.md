# Releasing jobwatch-native

The fast and slow timers run `~/apps/jobwatch-release`, a symlink to a built worktree of one commit; they never run
the editable checkout in `~/apps/jobwatch-native`, so editing that checkout cannot reach a live run.

Release: `deploy/release.sh <sha>` builds the commit under `~/projects/.worktrees/jobwatch-release-<shortsha>`,
checks that it imports, and swaps the symlink atomically. It prints the previous target. The next timer tick uses it;
nothing restarts by itself.

Undo: `ln -sfn <previous target> ~/apps/jobwatch-release` (the script prints the exact command).

Install the two drop-ins in `systemd/` as
`~/.config/systemd/user/jobwatch-native-{fast,slow}.service.d/60-release-copy.conf`, then
`systemctl --user daemon-reload`. Do not restart a running unit.

Old checkouts stay for as long as you keep them: `git -C ~/apps/jobwatch-native worktree remove ~/projects/.worktrees/jobwatch-release-<shortsha>`.
