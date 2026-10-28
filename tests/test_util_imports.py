"""Regression: modules moved into jobwatch/util/ (2b65652) kept one-dot lazy imports such as
`from .apply.render import ...`, which resolve to the missing jobwatch.util.apply and only fail at call time.
The autouse place fixture in conftest hides this, so these tests call the real code paths."""
import ast
import importlib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _relative_imports():
    for path in (ROOT / "jobwatch").rglob("*.py"):
        rel = path.relative_to(ROOT).with_suffix("")
        package = list(rel.parts[:-1]) if path.name != "__init__.py" else list(rel.parts[:-1])
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level:
                base = package[:len(package) - (node.level - 1)]
                yield path, node, base


def test_every_relative_import_in_jobwatch_resolves():
    broken = []
    for path, node, base in _relative_imports():
        # `from . import x` may name a submodule or something defined in the package itself: check the package.
        parts = base + node.module.split(".") if node.module else base
        if parts:
            target = ROOT.joinpath(*parts)
            if not (target.with_suffix(".py").exists() or target.is_dir()):
                broken.append(str(path.relative_to(ROOT)) + ":" + str(node.lineno) + " -> " + ".".join(parts))
    assert not broken, broken


def test_place_reads_the_real_profile(tmp_path, monkeypatch):
    import jobwatch.util.place as place
    importlib.reload(place)  # drop the conftest stub so the real lazy import runs
    (tmp_path / "profile.yaml").write_text(yaml.safe_dump({"candidate": {
        "location": "Exampleton, NSW", "timezone": "Australia/Sydney"}}))
    monkeypatch.setenv("JOBWATCH_PROFILE_DIR", str(tmp_path))
    assert place.person_state() == "NSW"
    assert str(place.person_timezone()) == "Australia/Sydney"
