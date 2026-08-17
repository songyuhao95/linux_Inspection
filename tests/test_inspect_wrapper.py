"""T-109 inspect.sh wrapper contract tests."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "inspect.sh"


def test_wrapper_static_contract():
    source = WRAPPER.read_text(encoding="utf-8")
    assert "runtime/bin/python3.12" in source
    assert "3.12" in source
    assert "INSPECT_ENABLE_REAL=1" in source
    assert "INSPECT_ENABLE_LOCAL_REAL=1" in source
    assert "trap cleanup EXIT" in source
    assert "trap 'exit 129' HUP" in source
    assert "trap 'exit 130' INT" in source
    assert "trap 'exit 143' TERM" in source
    assert 'exec "$PY"' not in source
    assert "ANSIBLE_PASSWORD" in source
    assert "SSHPASS" in source
    assert "INSPECT_RUNTIME_ROOT" in source


def test_wrapper_query_uses_project_runtime_without_system_fallback():
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash is not available on this control host")
    env = os.environ.copy()
    env.pop("INSPECT_FIXTURE_DIR", None)
    env["PYTHON3"] = "definitely-not-a-system-interpreter"
    proc = subprocess.run(
        [bash, str(WRAPPER), "--list-metrics"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "local.cpu.utilization" in proc.stdout


def test_wrapper_uses_project_runtime_for_all_modes():
    source = WRAPPER.read_text(encoding="utf-8")
    assert 'PY="$RUNTIME_ROOT/bin/python3.12"' in source
    assert 'for cand in "${PYTHON3:-}" python3 python' not in source
    assert 'export PYTHONPATH="$SCRIPT_DIR"' in source


def test_parent_environment_is_not_modified_by_subprocess():
    env = os.environ.copy()
    env["INSPECT_ENABLE_REAL"] = "sentinel"
    child = subprocess.run(
        [os.environ.get("COMSPEC", "cmd.exe"), "/c", "set INSPECT_ENABLE_REAL"],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert "sentinel" in child.stdout
    assert os.environ.get("INSPECT_ENABLE_REAL") != "sentinel"
