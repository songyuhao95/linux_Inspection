"""Minimal structured JSON stdout callback for the bundled Ansible runtime."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ansible.plugins.callback import CallbackBase


DOCUMENTATION = r"""
    name: json
    type: stdout
    short_description: emit a bounded JSON playbook result
    version_added: "2.18"
    description:
      - Emits only the result fields consumed by the inspection runner.
      - This project-local callback replaces the json callback that is not part of ansible-core.
    requirements:
      - enabled through ANSIBLE_CALLBACK_PLUGINS
"""


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "stdout"
    CALLBACK_NAME = "json"

    def __init__(self) -> None:
        super().__init__()
        self._plays: list[Dict[str, Any]] = []
        self._current_play: Optional[Dict[str, Any]] = None
        self._current_task: Optional[Dict[str, Any]] = None

    @staticmethod
    def _task_name(task: Any) -> str:
        return str(getattr(task, "name", "") or "")

    @staticmethod
    def _host_name(result: Any) -> str:
        host = getattr(result, "_host", None)
        return str(host.get_name() if host is not None else "")

    @staticmethod
    def _result_payload(result: Any, *, status: str) -> Dict[str, Any]:
        raw = getattr(result, "_result", {}) or {}
        if not isinstance(raw, dict):
            raw = {}
        payload: Dict[str, Any] = {"status": status}
        for key in ("stdout", "stderr", "rc", "failed", "unreachable", "skipped", "changed", "msg", "skip_reason"):
            if key in raw:
                value = raw[key]
                if isinstance(value, (str, int, float, bool)) or value is None:
                    payload[key] = value
                else:
                    payload[key] = str(value)
        payload.setdefault("failed", status == "failed")
        payload.setdefault("unreachable", status == "unreachable")
        payload.setdefault("skipped", status == "skipped")
        return payload

    def v2_playbook_on_play_start(self, play: Any) -> None:
        self._current_play = {"play": {"name": str(getattr(play, "name", "") or "")}, "tasks": []}
        self._plays.append(self._current_play)
        self._current_task = None

    def v2_playbook_on_task_start(self, task: Any, is_conditional: bool) -> None:
        if self._current_play is None:
            self._current_play = {"play": {"name": ""}, "tasks": []}
            self._plays.append(self._current_play)
        self._current_task = {"task": {"name": self._task_name(task)}, "hosts": {}}
        self._current_play["tasks"].append(self._current_task)

    def _record(self, result: Any, *, status: str) -> None:
        if self._current_task is None:
            return
        host_name = self._host_name(result)
        if not host_name:
            return
        self._current_task["hosts"][host_name] = self._result_payload(result, status=status)

    def v2_runner_on_ok(self, result: Any) -> None:
        self._record(result, status="ok")

    def v2_runner_on_changed(self, result: Any) -> None:
        self._record(result, status="changed")

    def v2_runner_on_failed(self, result: Any, ignore_errors: bool = False) -> None:
        self._record(result, status="failed")

    def v2_runner_on_unreachable(self, result: Any) -> None:
        self._record(result, status="unreachable")

    def v2_runner_on_skipped(self, result: Any) -> None:
        self._record(result, status="skipped")

    def v2_playbook_on_stats(self, stats: Any) -> None:
        summary: Dict[str, Any] = {}
        processed = getattr(stats, "processed", {}) or {}
        for host_name in processed:
            data: Dict[str, Any] = {}
            for key in ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored"):
                value = getattr(stats, key, {}).get(host_name, 0)
                data[key] = int(value)
            summary[str(host_name)] = data
        print(json.dumps({"plays": self._plays, "stats": summary}, ensure_ascii=False, separators=(",", ":")))
