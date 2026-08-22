"""Direct local collector.

``--local`` deliberately bypasses Ansible.  The project-local Python process
runs the same allow-listed probe and metric commands directly through bash;
remote selections continue to use ``inspect.ansible_runner`` and the bundled
Ansible runtime.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from inspect import ansible_runner as runner_mod
from inspect import probe as probe_mod


class LocalExecutionError(Exception):
    """A local collector setup or contract error (CLI exit code 10)."""

    exit_code = 10


_SECRET_ENV_NAMES = (
    "ANSIBLE_PASSWORD",
    "ANSIBLE_NET_PASSWORD",
    "SSHPASS",
    runner_mod.REAL_EXEC_ENV_VAR,
    runner_mod.LOCAL_REAL_ENV_VAR,
    runner_mod.REMOTE_USER_ENV_VAR,
    runner_mod.ASK_PASS_ENV_VAR,
)


def _clean_local_env() -> Dict[str, str]:
    env = os.environ.copy()
    for name in _SECRET_ENV_NAMES:
        env.pop(name, None)
    return env


def _error(code: str, message: str) -> Dict[str, str]:
    return {
        "code": code,
        "message": message,
        "metric_status": runner_mod.METRIC_ERROR_STATUS,
    }


def _run_shell(
    bash_path: str,
    command: str,
    timeout_sec: int,
    *,
    env: Dict[str, str],
    cwd: Path,
) -> Tuple[int, str, str]:
    """Run one allow-listed command without invoking Ansible."""
    try:
        completed = subprocess.run(
            [bash_path, "-lc", command],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            # The shell process itself must honor the same global ceiling as
            # the GNU timeout wrapper inside the command. Do not add a grace
            # period here: a hung child must become UNKNOWN promptly.
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        return runner_mod.TIMEOUT_RC, stdout, stderr
    except OSError as exc:
        # Keep the message category-only.  Do not leak host paths or inherited
        # environment values into the fact source or report.
        return runner_mod.TIMEOUT_RC, "", f"local shell unavailable: {type(exc).__name__}"
    return completed.returncode, completed.stdout, completed.stderr


def _fixture_result(
    selection: Any,
    specs: Sequence[runner_mod.CommandSpec],
    fixture_dir: Path,
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    """Reuse the existing fixture reader; it does not create a playbook or connect."""
    plan = runner_mod.RunPlan(
        playbook_path=Path(".runtime") / "local-fixture-unused.yml",
        inventory_file=Path(getattr(selection, "inventory_file", ".runtime/local-fixture-unused.ini")),
        hosts=list(selection.hosts),
        limit=getattr(selection, "limit", None),
        metric_specs=list(specs),
        probe_command=probe_mod.build_probe_command(
            timeout_sec=timeout_sec or runner_mod.PROBE_TIMEOUT_SEC
        ),
        selection_kind="local",
        nginx_whitelist=tuple(nginx_whitelist or ()),
        keepalived_whitelist=tuple(keepalived_whitelist or ()),
        elasticsearch_whitelist=tuple(elasticsearch_whitelist or ()),
        timeout_sec=timeout_sec or runner_mod.PROBE_TIMEOUT_SEC,
    )
    result = runner_mod._execute_fixture(plan, fixture_dir)
    result["local_mode"] = True
    return result


def run_local(
    selection: Any,
    specs: Sequence[runner_mod.CommandSpec],
    fixture_dir: Optional[Path] = None,
    runtime_dir: Optional[Path] = None,
    nginx_whitelist: Optional[Sequence[str]] = None,
    keepalived_whitelist: Optional[Sequence[str]] = None,
    elasticsearch_whitelist: Optional[Sequence[str]] = None,
    timeout_sec: Optional[int] = None,
) -> Dict[str, Any]:
    """Collect the selected local host directly; never call Ansible."""
    del runtime_dir  # kept for the CLI runner signature symmetry
    if getattr(selection, "kind", None) != "local":
        raise LocalExecutionError("本地执行器只接受 --local 主机选择")
    if not selection.hosts:
        raise LocalExecutionError("本地执行器没有可巡检主机")

    runner_mod.validate_command_specs(specs)
    resolved_fixture = runner_mod._resolve_fixture_dir(fixture_dir)
    if resolved_fixture is not None:
        return _fixture_result(
            selection,
            specs,
            resolved_fixture,
            nginx_whitelist=nginx_whitelist,
            keepalived_whitelist=keepalived_whitelist,
            elasticsearch_whitelist=elasticsearch_whitelist,
            timeout_sec=timeout_sec,
        )

    bash_path = shutil.which("bash")
    host = selection.hosts[0]
    started = time.monotonic()
    if not bash_path:
        host_result = runner_mod.build_host_result(
            host,
            {},
            False,
            [],
            host_error=_error(
                runner_mod.ERROR_PROBE_FAILED,
                "本地 shell 不可用（未找到 bash；local 不回退到 Ansible）",
            ),
            elapsed_sec=time.monotonic() - started,
        )
        return {
            "execution_status": runner_mod.STATUS_ERROR,
            "hosts": [host_result],
            "local_mode": True,
            "fixture_mode": False,
            "duration_sec": round(time.monotonic() - started, 3),
        }

    env = _clean_local_env()
    repo_root = Path(__file__).resolve().parent.parent
    effective_timeout_sec = timeout_sec or runner_mod.PROBE_TIMEOUT_SEC
    probe_rc, probe_stdout, probe_stderr = _run_shell(
        bash_path,
        probe_mod.build_probe_command(timeout_sec=effective_timeout_sec),
        effective_timeout_sec,
        env=env,
        cwd=repo_root,
    )
    probe_matrix = probe_mod.parse_probe_output(probe_stdout)
    probe_ok = probe_mod.probe_status(probe_matrix) == probe_mod.PROBE_OK
    if probe_rc == runner_mod.TIMEOUT_RC:
        host_error = _error(
            runner_mod.ERROR_TIMEOUT,
            "本地能力探测超时（local 不回退到 Ansible）",
        )
        host_result = runner_mod.build_host_result(
            host, probe_matrix, False, [], host_error=host_error,
            elapsed_sec=time.monotonic() - started,
        )
        return {
            "execution_status": runner_mod.STATUS_ERROR,
            "hosts": [host_result],
            "local_mode": True,
            "fixture_mode": False,
            "duration_sec": round(time.monotonic() - started, 3),
        }
    if not probe_ok:
        host_result = runner_mod.build_host_result(
            host,
            probe_matrix,
            False,
            [],
            host_error=_error(
                runner_mod.ERROR_PROBE_FAILED,
                "本地能力探测失败（bash 不可用或探测未执行；local 不回退到 Ansible）",
            ),
            elapsed_sec=time.monotonic() - started,
        )
        return {
            "execution_status": runner_mod.STATUS_ERROR,
            "hosts": [host_result],
            "local_mode": True,
            "fixture_mode": False,
            "duration_sec": round(time.monotonic() - started, 3),
        }

    metric_results = []
    for spec in specs:
        if spec.command is None and spec.error_code == runner_mod.ERROR_UNSUPPORTED_PROFILE:
            result = runner_mod.classify_metric_result(
                    spec.metric_id,
                    None,
                    "",
                    "",
                    spec.required_commands,
                    probe_matrix,
                    preset_error={
                        "code": runner_mod.ERROR_UNSUPPORTED_PROFILE,
                        "message": spec.error_message or "",
                    },
                )
            result["command"] = spec.command or ""
            if spec.replay_command is not None:
                result["replay_command"] = spec.replay_command
            metric_results.append(result)
            continue
        if spec.command is None:
            raise LocalExecutionError(
                f"指标 {spec.metric_id} 未生成可执行命令: {spec.error_code or 'unknown'}"
            )
        metric_env = dict(env)
        metric_env.update(getattr(spec, "task_environment", {}))
        rc, stdout, stderr = _run_shell(
            bash_path,
            spec.command,
            spec.timeout_sec,
            env=metric_env,
            cwd=repo_root,
        )
        result = runner_mod.classify_metric_result(
                spec.metric_id,
                rc,
                stdout,
                stderr,
                spec.required_commands,
                probe_matrix,
            )
        result["command"] = spec.command
        if spec.replay_command is not None:
            result["replay_command"] = spec.replay_command
        metric_results.append(result)

    metric_results = runner_mod.select_nginx_metrics(
        metric_results,
        host_ip=str(host.ip),
        nginx_whitelist=nginx_whitelist,
    )
    metric_results = runner_mod.select_keepalived_metrics(
        metric_results,
        host_ip=str(host.ip),
        keepalived_whitelist=keepalived_whitelist,
    )
    metric_results = runner_mod.select_elasticsearch_metrics(
        metric_results,
        host_ip=str(host.ip),
        elasticsearch_whitelist=elasticsearch_whitelist,
    )
    host_result = runner_mod.build_host_result(
        host,
        probe_matrix,
        True,
        metric_results,
        elapsed_sec=time.monotonic() - started,
    )
    return {
        "execution_status": runner_mod.run_status_for_hosts([host_result]),
        "hosts": [host_result],
        "local_mode": True,
        "fixture_mode": False,
        "duration_sec": round(time.monotonic() - started, 3),
    }


__all__ = ["LocalExecutionError", "run_local"]
