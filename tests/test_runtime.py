"""T-109 project-local runtime contract tests."""
import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("t109_runtime", ROOT / "inspect" / "runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
assert SPEC.loader is not None
SPEC.loader.exec_module(runtime)


def _manifest(root: Path, sha256=None):
    (root / "bin").mkdir(parents=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "python": {"path": "bin/python3.12", "version": "3.12.x", "sha256": sha256},
                "ansible": {"module": "ansible.cli.playbook"},
            }
        ),
        encoding="utf-8",
    )
    python_path = root / "bin" / "python3.12"
    python_path.write_text("placeholder", encoding="utf-8")
    if os.name != "nt":
        python_path.chmod(python_path.stat().st_mode | stat.S_IXUSR)
    return python_path


def test_missing_runtime_fails_closed(tmp_path):
    (tmp_path / "manifest.json").write_text(
        json.dumps({"schema": 1, "python": {"path": "bin/python3.12", "version": "3.12.x"}}),
        encoding="utf-8",
    )
    with pytest.raises(runtime.RuntimeContractError, match="missing"):
        runtime.resolve_runtime(tmp_path)


def test_runtime_version_mismatch_fails_closed(tmp_path, monkeypatch):
    _manifest(tmp_path)
    monkeypatch.setattr(runtime, "_probe_version", lambda path: "3.11.9")
    with pytest.raises(runtime.RuntimeVersionError, match="3.12"):
        runtime.resolve_runtime(tmp_path)


def test_runtime_success_and_same_runtime_ansible_argv(tmp_path, monkeypatch):
    python_path = _manifest(tmp_path)
    monkeypatch.setattr(runtime, "_probe_version", lambda path: "3.12.4")
    info = runtime.resolve_runtime(tmp_path)
    assert info.python_path == python_path.resolve()
    argv = info.ansible_playbook_argv(["playbook.yml", "-i", "hosts"])
    assert argv[:3] == [str(python_path.resolve()), "-m", "ansible.cli.playbook"]
    assert "ansible-playbook" not in argv


def test_fixture_mode_is_explicit_and_non_real():
    assert runtime.is_fixture_mode({"INSPECT_FIXTURE_DIR": "tests/fixtures/e2e"})
    assert not runtime.is_fixture_mode({"INSPECT_ENABLE_REAL": "1"})
    assert runtime.current_python_for_non_real() == sys.executable


def test_manifest_hash_mismatch_fails_closed(tmp_path, monkeypatch):
    _manifest(tmp_path, sha256="0" * 64)
    monkeypatch.setattr(runtime, "_probe_version", lambda path: "3.12.4")
    with pytest.raises(runtime.RuntimeContractError, match="sha256"):
        runtime.resolve_runtime(tmp_path)
