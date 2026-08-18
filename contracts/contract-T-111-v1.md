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
      "test_command": "bash inspect.sh --local"
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('tools/build-runtime.sh').read_text(); assert '.as_posix()' in s\""
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
  "contract_id": "contract-T-111-v1",
  "contract_sha256": "sha256:1d130c21c1f891d8f8846f219d523581fed98929ff91f8a55e13191b0e4297f0",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/runtime.py",
      "required": true
    },
    {
      "kind": "packaging-tool",
      "path": "tools/build-runtime.sh",
      "required": true
    },
    {
      "kind": "runtime-metadata",
      "path": "runtime/manifest.json",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_runtime.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "relay.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-110"
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
  "idempotency_key": "T-111",
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [
    "authorized VM 192.168.0.101:22 for test only"
  ],
  "non_goals": [
    "do not weaken hash verification",
    "do not use system Python/Ansible",
    "do not claim real business success"
  ],
  "objective": "Fix cross-platform bundled Ansible hash verification so the hash materializer and resolver use one canonical path encoding and the checked-in manifest matches the materialized runtime on the authorized Kylin VM.",
  "owned_paths": [
    "inspect/runtime.py",
    "tools/build-runtime.sh",
    "runtime/manifest.json",
    "tests/test_runtime.py",
    "relay.md"
  ],
  "parent_task_id": "T-110",
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
      "diagnose manifest/bundle hash mismatch",
      "canonicalize bundle hash path names",
      "regenerate manifest hash from committed bundle",
      "authorized VM smoke verification"
    ]
  },
  "success_definition": "The materializer and resolver hash the same bundle bytes and canonical POSIX relative paths; manifest verification passes on the authorized Kylin VM; focused tests and self-checks pass; no system fallback is introduced.",
  "task_id": "T-111",
  "timeout_minutes": 60,
  "verification_required": false,
  "worktree": null
}

```

# Task T-111

Fix the cross-platform bundled Ansible SHA-256 mismatch reported by kylin01.
