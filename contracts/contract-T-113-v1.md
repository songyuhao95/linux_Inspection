```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_modules.py tests/test_local_runner.py tests/test_inspect_wrapper.py tests/test_cli.py -q"
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
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -c \"from inspect import local_runner; assert local_runner\""
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
  "contract_id": "contract-T-113-v1",
  "contract_sha256": "sha256:a377c0cf3fc5acd6d2825293c22829661a928350c8f5cdf86e42e38b251c9619",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "module-registry",
      "path": "inspect/modules/",
      "required": true
    },
    {
      "kind": "local-runner",
      "path": "inspect/local_runner.py",
      "required": true
    },
    {
      "kind": "cli-integration",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "launcher",
      "path": "inspect.sh",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_local_runner.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "relay.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-112"
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
  "idempotency_key": "T-113",
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [
    "authorized VM 192.168.0.101:22 for test only"
  ],
  "non_goals": [
    "do not add CLI options",
    "do not change host-result-v1 schema",
    "do not weaken runtime hash verification",
    "do not use system Python/Ansible",
    "do not claim business success from a control smoke"
  ],
  "objective": "Introduce an explicit project-local monitor module registry and execution interface; execute --local directly with the project Python and shell without Ansible, while keeping -H/--hosts and -i/--inventory on the bundled Ansible path.",
  "owned_paths": [
    "inspect/modules/",
    "inspect/local_runner.py",
    "inspect/cli.py",
    "inspect/ansible_runner.py",
    "inspect.sh",
    "tests/test_modules.py",
    "tests/test_local_runner.py",
    "tests/test_inspect_wrapper.py",
    "README.md",
    "relay.md",
    "contracts/contract-T-113-v1.md"
  ],
  "parent_task_id": "T-112",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "new CLI options",
      "system package installation",
      "VM deployment beyond smoke test",
      "credential changes",
      "protected workflow artifacts"
    ],
    "include": [
      "explicit monitor registry and interface",
      "local direct collector",
      "remote bundled Ansible routing",
      "focused tests and documentation",
      "authorized VM smoke verification"
    ]
  },
  "success_definition": "The default Linux module is registered through the project-local registry; --local never invokes Ansible and directly executes the allow-listed probes/metrics; -H/--hosts and -i/--inventory continue to invoke only the bundled Ansible runtime; tests, compileall, diff check, self-test, and authorized smoke evidence pass without touching protected paths.",
  "task_id": "T-113",
  "timeout_minutes": 60,
  "verification_required": false,
  "worktree": null
}

```

# Task T-113

Introduce modular monitor registration and make local inspection bypass Ansible while remote inspection uses the bundled Ansible runtime.
