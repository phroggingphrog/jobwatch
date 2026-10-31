#!/usr/bin/env bash
# Point ~/apps/jobwatch-release at one built revision. The timers run that copy, never the editable dev checkout,
# so an in-progress refactor can no longer reach a live run (34 ModuleNotFoundError runs, 28-29 Oct 2026).
set -euo pipefail

sha=${1:?usage: deploy/release.sh <git revision>}
repo=$(git -C "$(dirname "$0")/.." rev-parse --show-toplevel)
revision=$(git -C "$repo" rev-parse --verify "$sha^{commit}")
short=${revision:0:12}
target="$HOME/projects/.worktrees/jobwatch-release-$short"
link="$HOME/apps/jobwatch-release"

if [ ! -d "$target" ]; then
  git -C "$repo" worktree add --detach "$target" "$revision"
fi
(cd "$target" && uv sync --frozen --quiet)

# Smoke the built copy before anything points at it: a release that cannot import must never become the target.
# From inside the target: `python -c` also puts the caller's directory on sys.path.
(cd "$target" && .venv/bin/python -c "import jobwatch.cli, jobwatch.run, pipeline.agentic.service")
(cd "$target" && .venv/bin/jobwatch --help >/dev/null)

previous=$([ -L "$link" ] && readlink -f "$link" || true)
ln -sfn "$target" "$link"
echo "released $short -> $target"
if [ -n "$previous" ]; then
  echo "undo: ln -sfn $previous $link"
fi
