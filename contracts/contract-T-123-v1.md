```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q --basetemp=.test-tmp tests/test_render_stdout.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect tests"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "git diff --check"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test"
  ],
  "contract_id": "contract-T-123-v1",
  "contract_sha256": "sha256:bc4ff4e60bfb94609ca96bf3f9228241e00830af0d3729a0f71942ed35e9f384",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_stdout.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_render_stdout.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/local-metrics-requirements.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/host-result-v1.md",
      "required": true
    },
    {
      "kind": "contract",
      "path": "contracts/contract-T-123-v1.md",
      "required": true
    }
  ],
  "evidence_types": [
    "test-result",
    "diff",
    "self-test",
    "local-vm-run",
    "remote-vm-run"
  ],
  "forbidden_ops": [
    "deploy",
    "force_push",
    "secret_access",
    "git_reset_hard",
    "git_clean"
  ],
  "forbidden_paths": [
    "inspect/ansible_runner.py",
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "inventory/"
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "objective": "修正系统负载 stdout 的比值语义：实际负载/核数显示为等号，正常阈值固定显示为 <=1.00，避免把实际比值误写成阈值。",
  "owned_paths": [
    "inspect/render_stdout.py",
    "tests/test_render_stdout.py",
    "README.md",
    "docs/specs/local-metrics-requirements.md",
    "docs/specs/host-result-v1.md",
    "contracts/contract-T-123-v1.md"
  ],
  "parent_task_id": "T-122",
  "phase": "implement",
  "risk_level": "low",
  "run_id": "run-20260818-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "不改变 JSON 字段、采集命令、指标 ID、状态判定或阈值逻辑",
      "不修改 Ansible 执行链路"
    ],
    "include": [
      "将正常输出从 负载/核数<=实际比值 改为 负载/核数=实际比值，阈值<=1.00，正常",
      "同步测试、README 和规格文档"
    ]
  },
  "success_definition": "正常窗口输出实际负载/核数=比值且固定阈值<=1.00；测试、compileall、自检、git diff --check 通过，远程测试不回归。",
  "task_id": "T-123",
  "timeout_minutes": 20,
  "verification_required": true
}

```

# T-123 修正负载比值与阈值的显示语义

当前输出示例中的 `负载/核数<=0.01` 把实际比值误写成了阈值。正确格式为：

`[OK] 15 分钟系统负载：0.05（15分钟，CPU核数=4，负载/核数=0.01，阈值<=1.00，正常）`

其中 `负载/核数` 是当前窗口的实际值，`<=1.00` 是固定的“不超过 CPU 核数”判定标准。

停止规则：不得改变采集、JSON 契约或状态判定；发现需要修改禁止路径时停止报告。
