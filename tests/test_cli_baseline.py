"""`jobwatch baseline` command: synthetic data only, everything under a temporary directory."""
import json
import os
import re
import sys
from pathlib import Path

from baseline_support import frozen, world  # noqa: F401  (fixtures)
from jobwatch import cli, users
from pipeline.agentic import baseline

REPO = Path(__file__).resolve().parents[1]
_FROZE = re.compile(r'^froze (bl-\d{8}T\d{6}Z-[0-9a-f]{8}): (\d+) cases, (\d+) skipped$')


def _transcript():
    return os.environ.get('JOBWATCH_PRINT_TRANSCRIPT') == '1'


def run(argv, capsys):
    rc = cli.main(argv)
    cap = capsys.readouterr()
    if _transcript():
        with capsys.disabled():
            print(f'$ jobwatch {" ".join(argv)}')
            print(cap.out, end='')
            print(cap.err, end='', file=sys.stderr)
    return rc, cap.out, cap.err


def _use_world(frozen, monkeypatch):
    monkeypatch.setenv('JOBWATCH_DB', str(frozen.config.db_path))


def test_cli_end_to_end(frozen, capsys, monkeypatch):
    _use_world(frozen, monkeypatch)
    rc, out, err = run(['baseline', 'freeze', '--limit', '2'], capsys)
    assert rc == 0 and err == ''
    match = _FROZE.match(out.strip())
    assert match and match.group(2) == '2' and match.group(3) == '0'
    bid = match.group(1)

    rc, out, _ = run(['baseline', 'list'], capsys)
    lines = out.strip().splitlines()
    assert rc == 0 and len(lines) == 1
    assert lines[0].startswith(bid) and 'cases=2' in lines[0]
    assert 'profile_version=2' in lines[0] and 'gate=pre_revision' in lines[0]

    rc, out, _ = run(['baseline', 'show', bid, '--cases'], capsys)
    assert rc == 0
    text = out.strip().splitlines()
    end = max(i for i, line in enumerate(text) if line == '}')
    shown = json.loads('\n'.join(text[:end + 1]))
    case_lines = text[end + 1:]
    assert shown['summary']['cases'] == 2
    assert shown['labels'] == {'labelled': 0, 'unlabelled': 2}
    assert shown['gate_state'] == 'pre_revision' and shown['gate_changed_since_freeze'] is False
    assert set(shown['missing_tags']) <= set(baseline.TAGS)
    assert 'case_sha256' not in shown
    assert len(case_lines) == 2
    cid = case_lines[0].split()[0]
    assert re.fullmatch(r'c-\d+-[0-9a-f]{8}', cid)
    # Ruling T6c: ids, counts and states only, never candidate or posting text.
    for word in ('Synthetic', 'Melbourne', 'Reconcile', 'example.invalid', 'Accounting'):
        assert word not in out

    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)   # the owner at a terminal
    rc, out, err = run(['baseline', 'label', bid, cid, '--suitable', 'yes', '--relevance', '3',
                        '--tag', 'stretch'], capsys)
    assert rc == 0 and out.strip() == f'labelled {cid}' and err == ''
    rc, out, _ = run(['baseline', 'show', bid], capsys)
    assert rc == 0 and json.loads(out)['labels'] == {'labelled': 1, 'unlabelled': 1}


def test_freeze_warns_when_the_gate_source_changed(frozen, capsys, monkeypatch):
    _use_world(frozen, monkeypatch)
    monkeypatch.setattr(baseline, 'PRE_REVISION_GATE_VERSION', '0' * 64)
    rc, out, err = run(['baseline', 'freeze', '--limit', '1'], capsys)
    assert rc == 0 and _FROZE.match(out.strip())
    assert 'warning: the gate source differs' in err
    bid = _FROZE.match(out.strip()).group(1)
    rc, out, _ = run(['baseline', 'show', bid], capsys)
    assert rc == 0 and json.loads(out)['gate_state'] == 'revised'
    rc, out, _ = run(['baseline', 'list'], capsys)
    assert 'gate=revised' in out


def test_list_with_no_baselines(frozen, capsys, monkeypatch):
    _use_world(frozen, monkeypatch)
    rc, out, err = run(['baseline', 'list'], capsys)
    assert rc == 0 and out.strip() == 'no baselines' and err == ''


def test_freeze_opens_the_database_read_only(frozen, capsys, monkeypatch):
    import sqlite3
    _use_world(frozen, monkeypatch)
    seen = []
    real = sqlite3.connect

    def spy(database, *args, **kwargs):
        seen.append((str(database), kwargs))
        return real(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', spy)
    rc, _, _ = run(['baseline', 'freeze', '--limit', '1'], capsys)
    assert rc == 0
    assert any(str(db).endswith('?mode=ro') and kw.get('uri') is True for db, kw in seen)


def test_cli_errors_print_the_code_and_exit_one(frozen, monkeypatch, capsys):
    # a friend with no profile
    users.create_user_dirs('friend')      # under the world's temporary data folder
    rc, out, err = run(['--user', 'friend', 'baseline', 'freeze'], capsys)
    assert rc == 1 and 'no_profile_version' in err and out == ''

    rc, out, err = run(['baseline', 'show', '../x'], capsys)
    assert rc == 1 and 'invalid_baseline_id' in err and out == ''

    _use_world(frozen, monkeypatch)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    rc, out, err = run(['baseline', 'freeze', '--limit', '1'], capsys)
    bid = _FROZE.match(out.strip()).group(1)
    cid = baseline.load_baseline(bid)[0].case_ids[0]
    rc, out, err = run(['baseline', 'label', bid, cid, '--relevance', '9'], capsys)
    assert rc == 1 and 'invalid_label' in err and out == ''
    assert baseline.read_labels(bid) == []


def test_label_command_refuses_without_a_terminal(frozen, capsys, monkeypatch):
    _use_world(frozen, monkeypatch)
    rc, out, _ = run(['baseline', 'freeze', '--limit', '1'], capsys)
    bid = _FROZE.match(out.strip()).group(1)
    cid = baseline.load_baseline(bid)[0].case_ids[0]
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    rc, out, err = run(['baseline', 'label', bid, cid, '--suitable', 'yes'], capsys)
    assert rc == 1 and 'human_required' in err and out == ''
    assert baseline.read_labels(bid) == []


def test_label_help_names_the_judgment_requirement(capsys):
    import pytest
    with pytest.raises(SystemExit):
        cli.main(['baseline', 'label', '--help'])
    out = ' '.join(capsys.readouterr().out.split())
    assert '--suitable, --relevance or --exclusion-violation' in out and '--tag' in out and 'note alone' in out


def test_label_commands_are_the_only_label_writers():
    allowed = {'pipeline/agentic/baseline.py', 'jobwatch/baseline_cli.py', 'jobwatch/evaluation_cli.py'}
    pattern = re.compile(r'\b(?:label_case|write_label)\(')
    found = set()
    for folder in ('jobwatch', 'pipeline'):
        for path in (REPO / folder).rglob('*.py'):
            if pattern.search(path.read_text(encoding='utf-8')):
                found.add(path.relative_to(REPO).as_posix())
    assert found and found <= allowed
