"""G0 real-runner unit tests using synthetic Ansible callback data only.

These tests never open a socket or invoke ansible-playbook. Live VM validation is
manual and explicitly gated outside the default pytest suite.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from inspect import ansible_runner as ar
from inspect import probe


class _FakeRuntime:
    """Synthetic dedicated runtime for callback tests; never launches Python."""

    python_path = Path("runtime/bin/python3.12")
    ansible_module = ar.runtime_contract.ANSIBLE_MODULE
    ansible_site_packages = Path("runtime/ansible/site-packages")
    ansible_collections_path = Path("runtime/ansible/collections")

    def ansible_playbook_argv(self, args):
        return [str(self.python_path), "-m", self.ansible_module, *map(str, args)]

    def ansible_environment(self, base_env):
        env = dict(base_env)
        for name in (
            "PYTHONPATH",
            "PYTHONHOME",
            "PYTHONUSERBASE",
            "VIRTUAL_ENV",
            "ANSIBLE_CONFIG",
            "ANSIBLE_HOME",
            "ANSIBLE_LIBRARY",
            "ANSIBLE_MODULE_UTILS",
            "ANSIBLE_LOOKUP_PLUGINS",
            "ANSIBLE_FILTER_PLUGINS",
            "ANSIBLE_ACTION_PLUGINS",
            "ANSIBLE_CALLBACK_PLUGINS",
            "ANSIBLE_COLLECTIONS_PATHS",
        ):
            env.pop(name, None)
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONPATH"] = str(self.ansible_site_packages)
        env["ANSIBLE_COLLECTIONS_PATHS"] = str(self.ansible_collections_path)
        return env


@pytest.fixture(autouse=True)
def _synthetic_runtime(monkeypatch):
    """Keep runner tests independent from the host's executable runtime."""
    monkeypatch.setattr(
        ar.runtime_contract, "resolve_runtime", lambda _root: _FakeRuntime()
    )


class Host:
    name = "node01"
    ip = "192.168.0.10"


def _probe_stdout():
    return "\n".join(f"/usr/bin/{command}" for command in probe.PROBE_COMMANDS)


def _plan(tmp_path, specs=None):
    specs = specs or [
        ar.CommandSpec(
            metric_id="local.cpu.load_1m",
            command="cat /proc/loadavg; nproc",
            timeout_sec=10,
            become=False,
            required_commands=("bash", "cat", "nproc"),
            source_anchor="test",
        )
    ]
    playbook = tmp_path / "playbook.yml"
    playbook.write_text("---\n", encoding="utf-8")
    return ar.RunPlan(
        playbook_path=playbook,
        inventory_file=tmp_path / "inventory.ini",
        hosts=[Host()],
        limit=None,
        metric_specs=specs,
        probe_command=probe.build_probe_command(),
    )


class LocalHost:
    name = "localhost"
    ip = "127.0.0.1"


def _local_plan(tmp_path, specs=None):
    plan = _plan(tmp_path, specs)
    inventory = tmp_path / "local-inventory.ini"
    inventory.write_text(
        "[all]\nlocalhost ansible_connection=local\n", encoding="utf-8"
    )
    plan.inventory_file = inventory
    plan.hosts = [LocalHost()]
    plan.selection_kind = "local"
    plan.cleanup_paths = (plan.playbook_path, inventory)
    return plan


def _payload(*, unreachable=False, host_name="node01"):
    host_value = {
        "rc": 0,
        "stdout": "0.42 0.30 0.20 1/123 10\n8\n",
        "stderr": "",
    }
    if unreachable:
        host_value = {"unreachable": True, "msg": "redacted transport detail"}
    return {
        "plays": [
            {
                "tasks": [
                    {
                        "task": {"name": "probe: 能力探测（15s）"},
                        "hosts": {host_name: {"stdout": _probe_stdout(), "rc": 0}},
                    },
                    {
                        "task": {"name": "metric: local.cpu.load_1m（10s）"},
                        "hosts": {host_name: host_value},
                    },
                ]
            }
        ],
        "stats": {host_name: {"unreachable": 1 if unreachable else 0}},
    }


def test_callback_success_maps_into_existing_host_shape(tmp_path):
    result = ar._parse_callback_results(_plan(tmp_path), _payload(), 0.25)
    assert len(result) == 1
    host = result[0]
    assert host["execution_status"] == ar.STATUS_SUCCESS
    assert host["host_error"] is None
    assert host["metrics"][0]["metric_id"] == "local.cpu.load_1m"
    assert host["metrics"][0]["error"] is None


def test_callback_bundle_is_split_back_into_individual_metrics(tmp_path):
    specs = [
        ar.CommandSpec(
            metric_id="local.cpu.load_1m",
            command="cat /proc/loadavg; nproc",
            timeout_sec=10,
            become=False,
            required_commands=("bash", "cat", "nproc"),
            source_anchor="test",
        ),
        ar.CommandSpec(
            metric_id="local.memory.available_percent",
            command="free -m",
            timeout_sec=10,
            become=False,
            required_commands=("bash", "free"),
            source_anchor="test",
        ),
    ]
    plan = _plan(tmp_path, specs)
    key, _bundle_specs = ar._metric_bundle_groups(specs)[0]
    task_name = ar._metric_bundle_task_name(0, key)
    bundle_stdout = (
        "INSPECT_METRIC_BEGIN\tlocal.cpu.load_1m\n"
        "0.42 0.30 0.20 1/123 10\n8\n"
        "INSPECT_METRIC_END\tlocal.cpu.load_1m\t0\n"
        "INSPECT_METRIC_BEGIN\tlocal.memory.available_percent\n"
        "Mem: 100 20 10 0 80 90\n"
        "INSPECT_METRIC_END\tlocal.memory.available_percent\t0\n"
    )
    payload = {
        "plays": [{
            "tasks": [
                {
                    "task": {"name": "probe: 能力探测（15s）"},
                    "hosts": {"node01": {"stdout": _probe_stdout(), "rc": 0}},
                },
                {
                    "task": {"name": task_name},
                    "hosts": {"node01": {"stdout": bundle_stdout, "rc": 0}},
                },
            ]
        }],
        "stats": {"node01": {"unreachable": 0}},
    }
    result = ar._parse_callback_results(plan, payload, 0.25)
    host = result[0]
    assert host["execution_status"] == ar.STATUS_SUCCESS
    assert [m["metric_id"] for m in host["metrics"]] == [
        "local.cpu.load_1m",
        "local.memory.available_percent",
    ]
    assert all(m["error"] is None for m in host["metrics"])


def test_callback_bundle_missing_marker_is_data_missing(tmp_path):
    specs = [
        ar.CommandSpec(
            metric_id="local.cpu.load_1m",
            command="cat /proc/loadavg; nproc",
            timeout_sec=10,
            become=False,
            required_commands=("bash", "cat", "nproc"),
            source_anchor="test",
        ),
        ar.CommandSpec(
            metric_id="local.memory.available_percent",
            command="free -m",
            timeout_sec=10,
            become=False,
            required_commands=("bash", "free"),
            source_anchor="test",
        ),
    ]
    plan = _plan(tmp_path, specs)
    key, _bundle_specs = ar._metric_bundle_groups(specs)[0]
    payload = {
        "plays": [{
            "tasks": [
                {
                    "task": {"name": "probe: 能力探测（15s）"},
                    "hosts": {"node01": {"stdout": _probe_stdout(), "rc": 0}},
                },
                {
                    "task": {"name": ar._metric_bundle_task_name(0, key)},
                    "hosts": {
                        "node01": {
                            "stdout": (
                                "INSPECT_METRIC_BEGIN\tlocal.cpu.load_1m\n"
                                "0.42 0.30 0.20 1/123 10\n8\n"
                                "INSPECT_METRIC_END\tlocal.cpu.load_1m\t0\n"
                            ),
                            "rc": 0,
                        }
                    },
                },
            ]
        }],
        "stats": {"node01": {"unreachable": 0}},
    }
    result = ar._parse_callback_results(plan, payload, 0.25)
    by_id = {m["metric_id"]: m for m in result[0]["metrics"]}
    assert by_id["local.cpu.load_1m"]["error"] is None
    assert by_id["local.memory.available_percent"]["error"]["code"] == ar.ERROR_DATA_MISSING


def test_callback_unreachable_is_connection_error_without_metrics(tmp_path):
    result = ar._parse_callback_results(
        _plan(tmp_path), _payload(unreachable=True), 0.25
    )
    host = result[0]
    assert host["execution_status"] == ar.STATUS_ERROR
    assert host["host_error"]["code"] == ar.ERROR_CONNECTION_FAILED
    assert host["metrics"] == []


def test_callback_parser_rejects_default_text():
    with pytest.raises(ar.RealExecutionError, match="JSON"):
        ar._load_callback_payload("PLAY RECAP node01 : ok=1 changed=0")


def test_real_execution_requires_explicit_gate(tmp_path, monkeypatch):
    monkeypatch.delenv(ar.REAL_EXEC_ENV_VAR, raising=False)
    with pytest.raises(ar.ExecutionNotReadyError):
        ar.execute_plan(_plan(tmp_path))


def test_real_execution_uses_json_callback_and_no_password_argv(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    payload = json.dumps(_payload(), ensure_ascii=False)
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = list(argv)
        calls["kwargs"] = kwargs
        return SimpleNamespace(stdout=payload, returncode=0)

    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.REMOTE_USER_ENV_VAR, "aqwh")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.delenv(ar.ASK_PASS_ENV_VAR, raising=False)
    monkeypatch.setattr(ar.subprocess, "run", fake_run)

    result = ar._execute_real(plan)
    assert result["real_mode"] is True
    assert result["execution_status"] == ar.STATUS_SUCCESS
    assert "--user" in calls["argv"]
    assert "aqwh" in calls["argv"]
    assert "--ask-pass" not in calls["argv"]
    assert calls["kwargs"]["shell"] is False
    assert calls["kwargs"]["env"]["ANSIBLE_STDOUT_CALLBACK"] == "json"
    assert not any("password" in item.lower() for item in calls["argv"])


def test_local_real_execution_requires_second_gate(tmp_path, monkeypatch):
    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.delenv(ar.LOCAL_REAL_ENV_VAR, raising=False)
    plan = _local_plan(tmp_path)
    with pytest.raises(ar.RealExecutionError, match="LOCAL_REAL"):
        ar._execute_real(plan)
    assert not plan.playbook_path.exists()
    assert not plan.inventory_file.exists()


def test_local_real_execution_is_credentialless(tmp_path, monkeypatch):
    plan = _local_plan(tmp_path)
    payload = json.dumps(_payload(host_name="localhost"), ensure_ascii=False)
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = list(argv)
        calls["kwargs"] = kwargs
        return SimpleNamespace(stdout=payload, returncode=0)

    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.LOCAL_REAL_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.delenv(ar.REMOTE_USER_ENV_VAR, raising=False)
    monkeypatch.delenv(ar.ASK_PASS_ENV_VAR, raising=False)
    monkeypatch.setenv("ANSIBLE_PASSWORD", "must-not-propagate")
    monkeypatch.setenv("ANSIBLE_NET_PASSWORD", "must-not-propagate")
    monkeypatch.setenv("SSHPASS", "must-not-propagate")
    monkeypatch.setattr(ar.subprocess, "run", fake_run)

    result = ar._execute_real(plan)
    assert result["execution_status"] == ar.STATUS_SUCCESS
    assert "--user" not in calls["argv"]
    assert "--ask-pass" not in calls["argv"]
    assert calls["kwargs"]["stdin"] is ar.subprocess.DEVNULL
    assert "ANSIBLE_PASSWORD" not in calls["kwargs"]["env"]
    assert "ANSIBLE_NET_PASSWORD" not in calls["kwargs"]["env"]
    assert "SSHPASS" not in calls["kwargs"]["env"]
    assert not any("password" in item.lower() for item in calls["argv"])
    assert not plan.playbook_path.exists()
    assert not plan.inventory_file.exists()


def test_local_real_execution_rejects_remote_credentials(tmp_path, monkeypatch):
    plan = _local_plan(tmp_path)
    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.LOCAL_REAL_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.setenv(ar.REMOTE_USER_ENV_VAR, "aqwh")
    with pytest.raises(ar.RealExecutionError, match="REMOTE_USER"):
        ar._execute_real(plan)


def test_local_real_execution_rejects_forged_local_inventory(tmp_path, monkeypatch):
    plan = _local_plan(tmp_path)
    plan.inventory_file.write_text("[all]\nlocalhost\n", encoding="utf-8")
    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.LOCAL_REAL_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    with pytest.raises(ar.RealExecutionError, match="ansible_connection=local"):
        ar._execute_real(plan)

def test_real_execution_requires_explicit_remote_user(tmp_path, monkeypatch):
    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.delenv(ar.REMOTE_USER_ENV_VAR, raising=False)
    with pytest.raises(ar.RealExecutionError, match="REMOTE_USER"):
        ar._execute_real(_plan(tmp_path))


def test_inventory_configured_auth_does_not_require_remote_env(
    tmp_path, monkeypatch
):
    plan = _plan(tmp_path)
    plan.selection_kind = "inventory"
    # Inventory controls the remote target scope; there is no project IP whitelist.
    plan.hosts[0].ip = "192.168.0.102"
    payload = json.dumps(_payload(), ensure_ascii=False)
    seen = {}

    def fake_run(argv, **kwargs):
        seen["argv"] = list(argv)
        return SimpleNamespace(stdout=payload, returncode=0)

    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.delenv(ar.REMOTE_USER_ENV_VAR, raising=False)
    monkeypatch.delenv(ar.ASK_PASS_ENV_VAR, raising=False)
    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    ar._execute_real(plan)
    assert "--user" not in seen["argv"]
    assert "--ask-pass" not in seen["argv"]


def test_real_execution_cleans_generated_runtime_files(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    generated = tmp_path / "generated-playbook.yml"
    generated.write_text("---\\n", encoding="utf-8")
    plan.cleanup_paths = (generated,)
    payload = json.dumps(_payload(), ensure_ascii=False)

    def fake_run(argv, **kwargs):
        return SimpleNamespace(stdout=payload, returncode=0)

    monkeypatch.setenv(ar.REAL_EXEC_ENV_VAR, "1")
    monkeypatch.setenv(ar.REMOTE_USER_ENV_VAR, "aqwh")
    monkeypatch.setenv("INSPECT_ALLOW_WINDOWS_REAL", "1")
    monkeypatch.setattr(ar.subprocess, "run", fake_run)
    ar._execute_real(plan)
    assert not generated.exists()


def test_callback_permission_failure_becomes_metric_unknown(tmp_path):
    payload = _payload()
    payload["plays"][0]["tasks"][1]["hosts"]["node01"] = {
        "rc": 1,
        "stdout": "",
        "stderr": "cat: /proc/loadavg: Permission denied",
        "failed": True,
    }
    result = ar._parse_callback_results(_plan(tmp_path), payload, 0.25)
    metric = result[0]["metrics"][0]
    assert metric["error"]["code"] == ar.ERROR_PERMISSION_DENIED
    assert metric["error"]["metric_status"] == "UNKNOWN"


    argv = ar.build_playbook_argv(
        Path("p.yml"), Path("i.ini"), remote_user="aqwh", ask_pass=True
    )
    assert "--user" in argv and "aqwh" in argv
    assert "--ask-pass" in argv
    assert argv[-1] == "--ask-pass"
