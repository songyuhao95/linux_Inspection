```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_ansible_callback.py tests/test_runtime.py tests/test_ansible_runner.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect tests"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "git diff --check"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "bash inspect.sh --local"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:git diff --check",
    "Bash:ssh authorized test VM"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-112-v1",
  "contract_sha256": "sha256:f1b1834bd3bb20a1f592916c19c79e87270b4514a06dfaa691ff1468bd1182e3",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "callback-plugin",
      "path": "inspect/callback_plugins/json.py",
      "required": true
    },
    {
      "kind": "runner-integration",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_ansible_callback.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "relay.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-111"
  ],
  "forbidden_ops": [
    "network installation",
    "system Ansible fallback",
    "force_push",
    "secret logging",
    "unauthorized hosts"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/"
  ],
  "idempotency_key": "T-112",
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [
    "authorized VM 192.168.0.101:22 for test only"
  ],
  "non_goals": [
    "do not weaken runtime hash verification",
    "do not use system Python/Ansible",
    "do not claim business success from a control smoke"
  ],
  "objective": "Provide a project-local structured JSON Ansible stdout callback because ansible-core 2.18.9 does not ship a json stdout callback, then use it from the bundled runtime without inheriting system callback plugins.",
  "owned_paths": [
    "inspect/callback_plugins/json.py",
    "inspect/ansible_runner.py",
    "tests/test_ansible_callback.py",
    "relay.md"
  ],
  "parent_task_id": "T-111",
  "phase": "verify",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "network package installation",
      "VM deployment beyond smoke test",
      "credential changes",
      "protected workflow artifacts"
    ],
    "include": [
      "project-local callback plugin",
      "runner environment wiring",
      "unit tests",
      "authorized VM smoke verification"
    ]
  },
  "success_definition": "The project-local Ansible callback emits the plays/tasks/hosts/stats JSON shape consumed by the runner; focused tests pass; the authorized Kylin VM reaches a structured callback result without using system Ansible or logging credentials.",
  "task_id": "T-112",
  "timeout_minutes": 60,
  "verification_required": false,
  "worktree": null
}

```

# Task T-112

Provide a project-local structured JSON callback for the bundled Ansible runtime.
