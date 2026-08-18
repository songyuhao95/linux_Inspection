```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_render_xlsx.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_cli.py"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-128-v1",
  "contract_sha256": "sha256:919bdb9c4aa0bc791ed56aaa9bd936ea01ec9f8037d15eaadf772e6b3e6ccf2a",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_xlsx.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_render_xlsx.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_cli.py",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff"
  ],
  "forbidden_ops": [
    "deploy",
    "force_push",
    "reset_hard",
    "clean",
    "secret_access"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "runtime/",
    "inventory/hosts.local.ini",
    "inspect/render_html.py",
    "inspect/templates/html-report-v1.html"
  ],
  "idempotency_key": "T-128-xlsx-real-ip",
  "input_artifacts": [
    {
      "path": "README.md",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/render_xlsx.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/cli.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "docs/specs/reporting-roadmap.md",
      "sha256": "",
      "version": "workspace"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "host_ips 参数仅由 CLI inventory 解析结果提供；独立 JSON 重渲染仍回退到事实源字段"
  ],
  "network_scope": [],
  "non_goals": [
    "不修改事实源 JSON 中的脱敏 IP",
    "不读取或打印凭据",
    "不改变指标采集语义"
  ],
  "objective": "修复 Excel Local 工作表的 IP 展示，使 CLI 生成的报表使用实际 inventory 目标地址而不是 JSON 脱敏占位符。",
  "output_schema": "task-report",
  "owned_paths": [
    "contracts/contract-T-128-v1.md",
    "inspect/render_xlsx.py",
    "inspect/cli.py",
    "tests/test_render_xlsx.py",
    "tests/test_cli.py"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-report-fixes",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "inspect/normalize.py",
      "host-result-v1 JSON schema",
      "HTML layout"
    ],
    "include": [
      "inspect/render_xlsx.py",
      "inspect/cli.py",
      "tests/test_render_xlsx.py",
      "tests/test_cli.py"
    ]
  },
  "success_definition": "inspect.sh 生成 Excel 时，Local.ip 对每个主机显示 inventory 中的 ansible_host/目标地址；事实源 JSON 脱敏契约不改变；无映射时保持安全回退。",
  "task_id": "T-128",
  "timeout_minutes": 45,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-128 Excel IP 展示修复

## 目标
让 Excel 报表的 Local.ip 列可用于运维定位：CLI 生成时显示实际 inventory 目标地址，同时不破坏 host-result-v1 的脱敏事实源。

## 实现要求
- `render_xlsx` 增加可选的主机名到目标地址映射；映射值只用于 Local.ip 展示。
- `inspect/cli.py` 从已解析的 host selection 构造映射并传入 Excel renderer。
- 独立调用 renderer 或缺少映射时保留当前安全回退行为。
- 增加测试覆盖直接 renderer 和 CLI 接线。

## 停止规则
不得修改 normalize.py 的 JSON 脱敏行为，不得读取真实凭据；发现报告安全边界与文档冲突时停止上报。
