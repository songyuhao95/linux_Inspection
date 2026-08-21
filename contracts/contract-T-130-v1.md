```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_ansible_runner.py tests/test_g0_remote_runner.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:git"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-130-v1",
  "contract_sha256": "sha256:acc344d831ae73c5d66f509775cddffe4f981548bc730c489ea482e0db37a971",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_ansible_runner.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_g0_remote_runner.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/ansible-execution.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-129"
  ],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff",
    "vm-smoke-timing"
  ],
  "forbidden_ops": [
    "force_push",
    "reset_hard",
    "clean",
    "secret_access"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "runtime/",
    "inventory/hosts.local.ini"
  ],
  "idempotency_key": "T-130-remote-module-bundles",
  "input_artifacts": [
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_ansible_runner.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_g0_remote_runner.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "docs/specs/ansible-execution.md",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "README.md",
      "sha256": "",
      "version": "workspace"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "保留 probe 闸门、每指标 timeout、allow-list、最小化 become 和单指标 UNKNOWN 语义",
    "bundle 输出使用受控 metric_id 标记，callback 缺失标记时仍按指标生成技术 UNKNOWN"
  ],
  "network_scope": [
    "用户授权的 192.168.0.101 测试 VM"
  ],
  "non_goals": [
    "不改变 host-result-v1 JSON 契约",
    "不改变 --local 的逐指标本地执行路径",
    "不将所有模块合并为一个不可隔离的超大远程命令",
    "不改变 serial:1 主机执行顺序"
  ],
  "objective": "将远程 Ansible 采集从每指标一个 raw 任务优化为每主机每模块一个 bundle 任务，同时保持单指标事实、错误分类、超时、权限和报表兼容。",
  "output_schema": "task-report",
  "owned_paths": [
    "contracts/contract-T-130-v1.md",
    "inspect/ansible_runner.py",
    "tests/test_ansible_runner.py",
    "tests/test_g0_remote_runner.py",
    "docs/specs/ansible-execution.md",
    "README.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260821-remote-bundles",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "local runner",
      "fact-source schema",
      "report renderers",
      "inventory credentials"
    ],
    "include": [
      "remote Ansible playbook generation",
      "structured callback parsing",
      "regression tests",
      "execution documentation"
    ]
  },
  "success_definition": "远程 playbook 对每个模块/权限组只生成一个 metric-bundle raw 任务；bundle 内每个指标仍有独立 timeout 和 metric_id 标记；callback 能拆回原有每指标结果并正确处理失败/缺失/连接错误；现有测试、自检通过，VM 三主机远程巡检成功且耗时低于当前 35.407 秒基线。",
  "task_id": "T-130",
  "timeout_minutes": 90,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-130 远程模块采集打包

## 实现约束

- 保留能力探测作为主机级连接闸门。
- 远程采集按 `linux`、`nginx`、`keepalived`、`elasticsearch` 分组；同一模块因 `become` 权限不同可拆成独立 bundle，避免扩大特权范围。
- bundle 只减少 Ansible/SSH 任务数量，不改变指标命令、指标 ID、命令证据、timeout 和 normalize 语义。
- bundle stdout 使用内部标记分隔每个指标，callback 控制端拆分后继续走既有 `classify_metric_result`。
- 未收到某个指标标记时必须生成 `ERROR_DATA_MISSING`，不得默认成功。

## 停止规则

发现 bundle 会泄漏秘密、破坏最小化 become、改变 host-result-v1 结构或无法保持单指标错误分类时停止并报告，不静默降级。
