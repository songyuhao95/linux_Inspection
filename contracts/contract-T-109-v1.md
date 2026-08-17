```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_runtime.py tests/test_inspect_wrapper.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_ansible_runner.py tests/test_fact_source.py -q"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/ -q"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "git diff --check"
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect.sh').read_text(); assert 'INSPECT_ENABLE_REAL' in s and '3.12' in s\""
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
  "contract_id": "contract-T-109-v1",
  "contract_sha256": "sha256:4a0bbabc5a0f450625dbec9e65d08f995e840d21103710efb1c4bf37fcc34c49",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect.sh",
      "required": true
    },
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
      "path": "inspect/fact_source.py",
      "required": true
    },
    {
      "kind": "runtime-metadata",
      "path": "runtime/manifest.json",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "runtime/README.md",
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
      "kind": "documentation",
      "path": "docs/local-vm-deploy.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/g0-real-vm.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff",
    "security-scan",
    "runtime-manifest"
  ],
  "forbidden_ops": [
    "deploy",
    "ssh",
    "ansible remote execution",
    "force_push",
    "secret_access",
    "runtime network install"
  ],
  "forbidden_paths": [
    "linux-docx/",
    "README.md",
    "contracts/contract-T-001-v1.md",
    "contracts/contract-T-001-v2.md",
    "contracts/contract-T-001-v3.md",
    "contracts/contract-T-001-v4.md",
    "run/events.ndjson",
    ".claude/",
    "run/reports/"
  ],
  "idempotency_key": "T-109",
  "input_artifacts": [
    {
      "path": "relay.md",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "inspect.sh",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "inspect/fact_source.py",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "pyproject.toml",
      "sha256": "",
      "version": "working-tree"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "fail closed when runtime is absent or version mismatched",
    "keep runtime artifact hash in manifest",
    "do not perform network installation",
    "keep real VM verification separate"
  ],
  "network_scope": [],
  "non_goals": [
    "Do not claim real VM success",
    "Do not download dependencies at runtime",
    "Do not use ordinary system-dependent venv as the only runtime",
    "Do not change protected historical files"
  ],
  "objective": "Implement a project-local Python 3.12 runtime contract and an inspect.sh wrapper that sets non-secret execution flags for one child process, invokes Ansible from the same runtime, and preserves secure cleanup and diagnostics.",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect.sh",
    "inspect/runtime.py",
    "inspect/ansible_runner.py",
    "inspect/fact_source.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "runtime/README.md",
    "runtime/manifest.json",
    "tools/build-runtime.sh",
    "tests/test_runtime.py",
    "tests/test_inspect_wrapper.py",
    "tests/test_ansible_runner.py",
    "tests/test_fact_source.py",
    "docs/local-vm-deploy.md",
    "docs/g0-real-vm.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "real VM deployment or SSH execution",
      "embedding credentials",
      "changing target allow-list or command allow-list",
      "rewriting historical contracts/reports/events"
    ],
    "include": [
      "project-local Python 3.12 runtime layout and manifest/build documentation",
      "inspect.sh runtime selection and environment lifecycle",
      "same-runtime Ansible invocation",
      "Python 3.7-compatible cleanup",
      "sanitized real execution diagnostics",
      "tests and deployment documentation"
    ]
  },
  "success_definition": "The wrapper never silently falls back to system Python or system ansible-playbook for real execution; local fixture execution works without manual INSPECT_* exports; cleanup and callback failures are classified without masking the primary error; tests and static scans pass.",
  "task_id": "T-109",
  "timeout_minutes": 60,
  "triggers": [
    "runtime packaging may be platform-specific"
  ],
  "verification_required": false,
  "worktree": null
}

```

# Task T-109

Implement the project-local Python 3.12 runtime contract and the inspect.sh wrapper described in relay.md. Prefer a runtime layout that can be populated from a verified offline archive; if the repository cannot carry the target Linux binary, provide a deterministic build tool and a manifest that makes the missing runtime fail closed. The wrapper must support fixture mode for local tests without enabling real execution, must set real-mode flags only inside its child environment, and must clean generated runtime files on normal, error, and signal exits. Ansible must be invoked through the dedicated runtime, not PATH lookup.

Do not perform network installation, remote execution, password handling, or edits outside owned paths. Do not claim VM success.
