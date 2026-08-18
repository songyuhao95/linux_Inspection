```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q --basetemp=.test-tmp tests/test_normalize.py tests/test_render_stdout.py"
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
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-120-v1",
  "contract_sha256": "sha256:a1004fa112788ee279d71779d189ef5e2fffcf1a320ff1b5094a94c714a66e96",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/normalize.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/render_stdout.py",
      "required": true
    },
    {
      "kind": "contract",
      "path": "inspect/schema/host-result-v1.schema.json",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_normalize.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_render_stdout.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/host-result-v1.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "schema-validation",
    "diff",
    "vm-run"
  ],
  "forbidden_ops": [
    "deploy",
    "force_push",
    "secret_access",
    "git_reset_hard",
    "git_clean"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "inspect/ansible_runner.py"
  ],
  "idempotency_key": "T-120",
  "input_artifacts": [
    {
      "path": "inspect/normalize.py",
      "sha256": "",
      "version": "fd7a882"
    },
    {
      "path": "inspect/render_stdout.py",
      "sha256": "",
      "version": "fd7a882"
    },
    {
      "path": "inspect/schema/host-result-v1.schema.json",
      "sha256": "",
      "version": "fd7a882"
    },
    {
      "path": "docs/specs/local-metrics-requirements.md",
      "sha256": "",
      "version": "fd7a882"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "明细状态由同一 normalize 判定逻辑生成；保留整体最大值状态用于兼容汇总"
  ],
  "network_scope": [],
  "non_goals": [
    "不改变磁盘指标整体状态按最大使用率聚合的语义"
  ],
  "objective": "修正磁盘与 inode 挂载点明细的状态展示，使每个挂载点按自身使用率判定 OK/WARN/CRIT/UNKNOWN，而指标整体状态继续按所有挂载点聚合用于主机摘要。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/normalize.py",
    "inspect/render_stdout.py",
    "inspect/schema/host-result-v1.schema.json",
    "tests/test_normalize.py",
    "tests/test_render_stdout.py",
    "docs/specs/host-result-v1.md",
    "docs/specs/local-metrics-requirements.md",
    "README.md",
    "contracts/contract-T-120-v1.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-002",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "其它 Linux 指标的阈值调整",
      "Ansible 采集流程重构",
      "HTML/XLSX 报表版式重构"
    ],
    "include": [
      "磁盘使用率与 inode 使用率的挂载点级状态",
      "host-result-v1 schema 的可选明细字段",
      "stdout 挂载点状态渲染",
      "相关单元测试、契约文档和 README 说明"
    ]
  },
  "success_definition": "JSON evidence.details 中每条文件系统明细带有与自身使用率一致的状态；stdout 对每个挂载点显示该明细状态；指标整体 status、execution_summary 和阈值行为保持最大值聚合兼容；相关测试和 Linux 虚拟机验证通过。",
  "task_id": "T-120",
  "timeout_minutes": 30,
  "triggers": [
    "用户发现挂载点复用整体状态导致健康挂载点误报"
  ],
  "verification_required": true,
  "worktree": null
}

```
---

# T-120 挂载点级状态修正

## 目标

当前 `evidence.details` 只有挂载点和使用率，终端渲染把 metric 级整体状态复制到每行，导致 `/dev 0%` 也显示 `[WARN]`，`/tmp 1%` 也显示 `[CRIT]`。本任务增加挂载点级状态，避免健康挂载点误报。

## 实现要求

- 对 `local.filesystem.used_percent` 和 `local.filesystem.inode_used_percent` 的每个明细按照自身 `used_percent` 使用现有阈值判定。
- JSON 中保留 metric 级 `status`、`normalized_value`、`raw_value`，继续按所有挂载点最大使用率聚合。
- JSON `evidence.details[]` 增加 `status`，必要时可增加简短判定注记，但不得改变既有字段语义。
- stdout 读取明细 `status`，每个挂载点显示独立徽标；旧 JSON 中没有明细状态时兼容回退到 metric 级状态。
- 不采集伪造数据，不在渲染层重新读取阈值或重新判定。
- schema、测试、开发文档同步更新。

## 停止规则

遇到现有阈值文档与实现冲突、需要改变整体聚合语义、或发现合同范围外文件必须修改时，停止并报告，不得猜测。
