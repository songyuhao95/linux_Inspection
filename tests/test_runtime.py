"""T-109/T-110 project-local Python and Ansible runtime contract tests."""
import hashlib
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
    site = root / "ansible" / "site-packages"
    (site / "ansible" / "cli").mkdir(parents=True)
    (root / "ansible" / "collections").mkdir(parents=True)
    (site / "ansible" / "__init__.py").write_text("__version__ = '2.18.0'\n", encoding="utf-8")
    (site / "ansible" / "cli" / "playbook.py").write_text("# bundled entry point\n", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "python": {"path": "bin/python3.12", "version": "3.12.x", "sha256": sha256},
                "ansible": {
                    "distribution": "ansible-core",
                    "status": "built",
                    "version": "2.18.0",
                    "site_packages": "ansible/site-packages",
                    "collections_path": "ansible/collections",
                    "module": "ansible.cli.playbook",
                },
            }
        ),
        encoding="utf-8",
    )
    python_path = root / "bin" / "python3.12"
    python_path.write_text("placeholder", encoding="utf-8")
    if os.name != "nt":
        python_path.chmod(python_path.stat().st_mode | stat.S_IXUSR)
    return python_path


def _stub_probes(monkeypatch, version="3.12.4"):
    monkeypatch.setattr(runtime, "_probe_version", lambda path: version)
    monkeypatch.setattr(
        runtime,
        "_probe_ansible",
        lambda python_path, site_packages, runtime_root: site_packages / "ansible" / "__init__.py",
    )


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
    _stub_probes(monkeypatch)
    info = runtime.resolve_runtime(tmp_path)
    assert info.python_path == python_path.resolve()
    assert info.ansible_site_packages == (tmp_path / "ansible" / "site-packages").resolve()
    argv = info.ansible_playbook_argv(["playbook.yml", "-i", "hosts"])
    assert argv[:3] == [str(python_path.resolve()), "-m", "ansible.cli.playbook"]
    assert "ansible-playbook" not in argv


def test_bundled_ansible_environment_replaces_inherited_system_paths(tmp_path, monkeypatch):
    _manifest(tmp_path)
    _stub_probes(monkeypatch)
    info = runtime.resolve_runtime(tmp_path)
    env = info.ansible_environment(
        {
            "PATH": "/usr/bin",
            "PYTHONPATH": "/system/site-packages",
            "ANSIBLE_CONFIG": "/etc/ansible/ansible.cfg",
            "ANSIBLE_COLLECTIONS_PATHS": "/system/collections",
        }
    )
    assert env["PYTHONPATH"] == str(info.ansible_site_packages)
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert "ANSIBLE_CONFIG" not in env
    assert env["ANSIBLE_COLLECTIONS_PATHS"] == str((tmp_path / "ansible" / "collections").resolve())


def test_bundled_ansible_missing_fails_closed(tmp_path, monkeypatch):
    _manifest(tmp_path)
    (tmp_path / "ansible" / "site-packages" / "ansible" / "cli" / "playbook.py").unlink()
    monkeypatch.setattr(runtime, "_probe_version", lambda path: "3.12.4")
    with pytest.raises(runtime.RuntimeContractError, match="entry point"):
        runtime.resolve_runtime(tmp_path)


def test_fixture_mode_is_explicit_and_non_real():
    assert runtime.is_fixture_mode({"INSPECT_FIXTURE_DIR": "tests/fixtures/e2e"})
    assert not runtime.is_fixture_mode({"INSPECT_ENABLE_REAL": "1"})
    expected = runtime.DEFAULT_RUNTIME_ROOT / "bin" / ("python3.12.exe" if os.name == "nt" else "python3.12")
    assert runtime.current_python_for_non_real() == str(expected)


def test_manifest_hash_mismatch_fails_closed(tmp_path, monkeypatch):
    _manifest(tmp_path, sha256="0" * 64)
    monkeypatch.setattr(runtime, "_probe_version", lambda path: "3.12.4")
    with pytest.raises(runtime.RuntimeContractError, match="sha256"):
        runtime.resolve_runtime(tmp_path)


def test_materializer_uses_posix_bundle_paths():
    source = (ROOT / "tools" / "build-runtime.sh").read_text(encoding="utf-8")
    assert "path.relative_to(root).as_posix()" in source
    assert "str(path.relative_to(root))" not in source

def test_bundle_hash_ignores_generated_bytecode(tmp_path):
    root = tmp_path / "ansible"
    root.mkdir()
    (root / "module.py").write_text("payload\n", encoding="utf-8")
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "module.cpython-312.pyc").write_bytes(b"generated")
    (root / "module.pyc").write_bytes(b"generated")
    runtime._verify_bundle_hash(root, digest.hexdigest())
