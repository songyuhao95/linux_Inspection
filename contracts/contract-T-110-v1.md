```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_runtime.py tests/test_inspect_wrapper.py tests/test_ansible_runner.py -q"
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
      "test_command": "python -c \"import json; d=json.load(open('runtime/manifest.json')); assert d['ansible']['site_packages']\""
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:git diff --check"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-110-v1",
  "contract_sha256": "sha256:c2877dfead19ba9804b7793965c622f9424f2af59e52c9a35be400e682371341",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/runtime.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect.sh",
      "required": true
    },
    {
      "kind": "runtime-metadata",
      "path": "runtime/manifest.json",
      "required": true
    },
    {
      "kind": "runtime-documentation",
      "path": "runtime/ansible/README.md",
      "required": true
    },
    {
      "kind": "runtime-lock",
      "path": "runtime/ansible/requirements.lock",
      "required": true
    },
    {
      "kind": "packaging-tool",
      "path": "tools/build-runtime.sh",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_runtime.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_inspect_wrapper.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_ansible_runner.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "runtime/README.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "relay.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-109"
  ],
  "evidence_types": [
    "test-result",
    "diff",
    "runtime-manifest",
    "security-scan"
  ],
  "forbidden_ops": [
    "deploy",
    "ssh",
    "ansible remote execution",
    "network install",
    "force_push",
    "secret_access"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/",
    "README.md",
    "contracts/contract-T-001-v1.md",
    "contracts/contract-T-001-v2.md",
    "contracts/contract-T-001-v3-v1.md"
  ],
  "idempotency_key": "T-110",
  "input_artifacts": [
    {
      "path": "inspect/runtime.py",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "runtime/manifest.json",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "tools/build-runtime.sh",
      "sha256": "",
      "version": "working-tree"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [],
  "non_goals": [
    "Do not claim an actual Linux bundle exists until an approved archive is materialized",
    "Do not use system ansible-playbook",
    "Do not perform network installation",
    "Do not claim real VM success"
  ],
  "objective": "Bundle Ansible inside the project-local offline runtime and make real inspection execution fail closed unless the dedicated Python imports the bundled Ansible package from the project runtime.",
  "owned_paths": [
    "inspect.sh",
    "inspect/runtime.py",
    "inspect/ansible_runner.py",
    "runtime/README.md",
    "runtime/manifest.json",
    "runtime/ansible/README.md",
    "runtime/ansible/requirements.lock",
    "tools/build-runtime.sh",
    "tests/test_runtime.py",
    "tests/test_inspect_wrapper.py",
    "tests/test_ansible_runner.py",
    "docs/local-vm-deploy.md",
    "docs/g0-real-vm.md",
    "relay.md"
  ],
  "parent_task_id": "T-109",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "network installation or dependency download",
      "real VM deployment, SSH, or Ansible remote execution",
      "credentials and password handling",
      "changing target or command allow-lists",
      "protected run/events.ndjson, .claude/, historical contracts, and historical reports"
    ],
    "include": [
      "runtime manifest metadata for bundled Ansible site-packages and module entry point",
      "offline runtime materializer validation for Python 3.12 and bundled ansible-core",
      "runtime resolver and subprocess environment isolation from system Ansible/PYTHONPATH",
      "inspect.sh and ansible_runner enforcement of project-internal Ansible",
      "regression tests and runtime documentation"
    ]
  },
  "success_definition": "The runtime manifest names a project-local Ansible bundle; the offline materializer rejects archives without ansible-core and the ansible.cli.playbook entry point; runtime resolution verifies the import path is inside runtime/; real subprocesses receive only the dedicated runtime package path and never rely on PATH or inherited system Python/Ansible paths; tests and static checks pass.",
  "task_id": "T-110",
  "timeout_minutes": 60,
  "verification_required": false,
  "worktree": null
}

```

# Task T-110

Bundle Ansible in the project-local offline runtime. Real execution must import `ansible.cli.playbook` from the runtime-owned package path and must fail closed if the bundle is absent, invalid, or resolves outside `runtime/`.
