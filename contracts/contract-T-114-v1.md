```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_linux_basic.py tests/test_modules.py tests/test_ansible_runner.py tests/test_local_runner.py"
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
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-5",
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
  "contract_id": "contract-T-114-v1",
  "contract_sha256": "sha256:5a8c759facf04f812fe10938860bd9027e526df718fffecb6da233a34b42a4c9",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "monitor-module",
      "path": "inspect/modules/linux_basic.py",
      "required": true
    },
    {
      "kind": "module-registry-update",
      "path": "inspect/modules/registry.py",
      "required": true
    },
    {
      "kind": "metric-collection",
      "path": "inspect/metrics.py",
      "required": true
    },
    {
      "kind": "runner-integration",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_linux_basic.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    }
  ],
  "forbidden_ops": [
    "network installation",
    "system Ansible fallback",
    "force_push",
    "secret logging",
    "unauthorized hosts",
    "modify protected workflow artifacts"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/"
  ],
  "idempotency_key": "T-114",
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [
    "authorized VM 192.168.0.101:22 for test only"
  ],
  "objective": "Add an independent linux_basic monitor module for generic Linux host metrics, including filesystem usage, memory availability, interval CPU utilization, load and swap, and persist the results through the existing host-result-v1 JSON fact source without changing the report contract.",
  "owned_paths": [
    "inspect/modules/",
    "inspect/metrics.py",
    "inspect/ansible_runner.py",
    "inspect/local_runner.py",
    "inspect/normalize.py",
    "inspect/cli.py",
    "tests/test_modules.py",
    "tests/test_ansible_runner.py",
    "tests/test_local_runner.py",
    "tests/test_metrics.py",
    "tests/test_linux_basic.py",
    "README.md",
    "relay.md",
    "contracts/contract-T-114-v1.md"
  ],
  "parent_task_id": "T-113",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "new CLI options",
      "middleware-specific profile implementation",
      "host-result-v1 schema redesign",
      "system Python or Ansible fallback",
      "credential changes or expanded remote targets",
      "protected workflow artifacts"
    ],
    "include": [
      "split generic Linux host metric ownership into inspect/modules/linux_basic.py",
      "keep profile-dependent process/service/port/log metrics in linux_common",
      "make generic filesystem metrics inspect the root filesystem by default",
      "sample CPU utilization over a one-second interval in both local and remote command paths",
      "add focused tests and documentation for module boundaries and JSON facts"
    ]
  },
  "success_definition": "The registry exposes a distinct linux_basic module; generic Linux metrics execute without profile configuration in --local and remote command specs; CPU utilization uses a one-second two-sample command; normalized host-result-v1 JSON contains the generic metric results; focused tests, compileall, diff check, assembly self-test, and the authorized VM local smoke pass.",
  "task_id": "T-114",
  "verification_required": true
}

```

# Task T-114

Implement a standalone Linux basic host metrics module and keep JSON facts as the single reporting source.
