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
  "contract_id": "contract-T-122-v1",
  "contract_sha256": "sha256:451480d38d80247d26e6decfe4be6f67ae5d978766afce2805bb2b8786ba556b",
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
      "path": "contracts/contract-T-122-v1.md",
      "required": true
    }
  ],
  "evidence_types": [
    "test-result",
    "diff",
    "self-test"
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
  "objective": "改进系统负载 stdout 展示：将原有文字判定改为括号内的直观解释，显示时间窗口、CPU 核数和负载/核数比值；继续从 JSON 事实源读取，不重新采集。",
  "owned_paths": [
    "inspect/render_stdout.py",
    "tests/test_render_stdout.py",
    "README.md",
    "docs/specs/local-metrics-requirements.md",
    "docs/specs/host-result-v1.md",
    "contracts/contract-T-122-v1.md"
  ],
  "parent_task_id": "T-121",
  "phase": "implement",
  "risk_level": "low",
  "run_id": "run-20260818-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "不改变采集命令、JSON 字段、指标 ID、状态判定或阈值",
      "不新增 5/15 分钟独立指标 ID",
      "不修改 Ansible 执行链路"
    ],
    "include": [
      "从 evidence.details 的 window/load/cpu_cores 渲染括号解释",
      "负载/核数按 JSON 中的负载和 CPU 核数计算并保留两位小数",
      "将正常窗口展示为负载/核数<=0.00 的用户指定格式；异常/未知窗口也保持信息真实",
      "同步 README 和正式规格中的示例"
    ]
  },
  "success_definition": "三行负载输出都使用括号解释，包含 1/5/15 分钟、CPU 核数和负载/核数；旧事实源无 details 时不崩溃；相关测试、compileall、自检、git diff --check 通过。",
  "task_id": "T-122",
  "timeout_minutes": 20,
  "verification_required": true
}

```

# T-122 系统负载解释文本优化

将负载指标从含糊的“负载 <= CPU 核数：正常”改为括号内的直观解释。输出应类似：

`[OK] 1 分钟系统负载：0.01（1分钟，CPU核数=8，负载/核数<=0.00）`

解释内容必须来自事实源 JSON 中已采集的 `window`、`load`、`cpu_cores`，渲染层不得重新采集或改变状态判定。

停止规则：如果需要新增指标 ID、改变负载状态判定或修改禁止路径，停止并报告。
