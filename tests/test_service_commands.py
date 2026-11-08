import shlex
from pathlib import Path

import pytest

from jobwatch import cli


ROOT = Path(__file__).resolve().parents[1]
COMMANDS = []
for directory in ('systemd', 'deploy'):
    for path in sorted((ROOT / directory).iterdir()):
        if path.suffix not in ('.service', '.conf'):
            continue
        for line in path.read_text().splitlines():
            key, _, value = line.partition('=')
            if key not in ('ExecStart', 'ExecStopPost') or not value:
                continue
            executable, *arguments = shlex.split(value)
            if executable.endswith('/jobwatch') and any(
                command in arguments for command in ('run', 'read', 'service-exit')
            ):
                COMMANDS.append(pytest.param(arguments, id=f'{path.relative_to(ROOT)}:{key}'))


@pytest.mark.parametrize('arguments', COMMANDS)
def test_service_command_runs_with_owner_only_cli(arguments, tmp_path, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DB', str(tmp_path / 'jobs.db'))
    monkeypatch.setenv('JOBWATCH_CONFIG_DIR', str(ROOT / 'config'))
    monkeypatch.setenv('SERVICE_RESULT', 'success')
    # An unconfirmed owner must stop collection/read before network or model work.
    monkeypatch.setattr(cli.discovery_gate, 'allowed', lambda command: False)
    try:
        result = cli.main(arguments)
    except SystemExit as exc:
        result = exc.code
    assert result == 0
