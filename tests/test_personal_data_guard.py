"""The personal-data guard: private config must not be tracked, and secrets/identifiers must not leak."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_personal_data.py"


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "add", "-f", "."], cwd=tmp_path, check=True)
    return tmp_path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args],
                          text=True, capture_output=True)


def test_private_config_must_not_be_tracked(tmp_path):
    root = _repo(tmp_path, {"config/rules.yaml": "arms: []\n", "config/rules.example.yaml": "arms: []\n"})
    result = _run(root)
    assert result.returncode == 1
    assert "config/rules.yaml" in result.stdout


def test_examples_only_is_clean(tmp_path):
    root = _repo(tmp_path, {"config/rules.example.yaml": "arms: []\n", "README.md": "# Jobwatch\n"})
    result = _run(root)
    assert result.returncode == 0, result.stdout + result.stderr


def test_private_key_material_is_refused(tmp_path):
    pem = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\nabc\n"   # split so this file never matches itself
    root = _repo(tmp_path, {"notes.txt": pem})
    result = _run(root)
    assert result.returncode == 1
    assert "private key" in result.stdout.lower()


def test_owner_identifiers_are_refused_when_supplied(tmp_path):
    root = _repo(tmp_path, {"config/search_notes.md": "Example Person\n"})
    assert _run(root).returncode == 0
    result = _run(root, "--identifiers", "Example Person")
    assert result.returncode == 1
    assert "config/search_notes.md" in result.stdout


def test_this_repository_is_clean():
    result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(ROOT)], text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
