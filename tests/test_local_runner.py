"""Tests for direct local collection, which must not invoke Ansible."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from inspect import ansible_runner as runner_mod
from inspect import local_runner
from inspect import probe as probe_mod
from inspect.inventory import HostEntry, HostSelection

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "raw"


def _local_selection(host_name="localhost"):
    host = HostEntry(name=host_name, ip="127.0.0.1")
    return HostSelection(
        kind="local",
        inventory_file=ROOT / ".runtime" / "unused-local.ini",
        hosts=[host],
    )


def test_local_fixture_path_does_not_call_ansible(monkeypatch):
    specs = runner_mod.build_metric_command_specs()
    monkeypatch.setattr(
        runner_mod,
        "run",
        lambda *args, **kwargs: pytest.fail("local fixture path must not call ansible runner"),
    )
    result = local_runner.run_local(_local_selection("node-a"), specs, fixture_dir=FIXTURES)
    assert result["local_mode"] is True
    assert result["fixture_mode"] is True
    assert result["hosts"][0]["host"] == "node-a"


def test_local_real_path_executes_bash_directly(monkeypatch):
    calls = []
    probe_stdout = "\n".join(f"/usr/bin/{name}" for name in probe_mod.PROBE_COMMANDS) + "\n"

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        command = argv[-1]
        if "command -v bash" in command:
            return SimpleNamespace(returncode=0, stdout=probe_stdout, stderr="")
        return SimpleNamespace(returncode=0, stdout="0\n", stderr="")

    monkeypatch.setattr(local_runner.shutil, "which", lambda name: "/bin/bash")
    monkeypatch.setattr(local_runner.subprocess, "run", fake_run)
    monkeypatch.setattr(
        runner_mod,
        "run",
        lambda *args, **kwargs: pytest.fail("local real path must not call ansible runner"),
    )

    result = local_runner.run_local(_local_selection(), runner_mod.build_metric_command_specs())
    assert result["local_mode"] is True
    assert result["fixture_mode"] is False
    assert result["hosts"][0]["probe_status"] == probe_mod.PROBE_OK
    assert calls
    assert all(call[0][0] == "/bin/bash" for call in calls)
    assert all("ansible-playbook" not in call[0][-1] for call in calls)


def test_local_runner_rejects_remote_selection():
    remote = HostSelection(
        kind="hosts",
        inventory_file=ROOT / ".runtime" / "unused.ini",
        hosts=[HostEntry(name="192.168.0.101", ip="192.168.0.101")],
    )
    with pytest.raises(local_runner.LocalExecutionError):
        local_runner.run_local(remote, runner_mod.build_metric_command_specs())
