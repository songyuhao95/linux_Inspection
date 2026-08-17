```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_render_stdout.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/render_stdout.py').read_text(encoding='utf-8'); assert 'execution_status' in s and 'UNKNOWN' in s\""
    }
  ],
  "allowed_tools": [
    "Read",
    "Glob",
    "Grep",
    "Write:owned_paths",
    "Edit:owned_paths",
    "Bash:python",
    "Bash:pytest",
    "Bash:git-status"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-105-v1",
  "contract_sha256": "sha256:2cdc574c228ef381334a83c07cff9ade8277289e2966991435baa42472b7777b",
  "contract_version": 1,
  "cost_required": false,
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
      "kind": "fixture",
      "path": "tests/fixtures/stdout/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-105.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-104"
  ],
  "dfm_required": false,
  "evidence_types": [
    "artifact",
    "documentation-validation",
    "structure-review",
    "git-diff"
  ],
  "forbidden_ops": [
    "target_host_access",
    "network_access",
    "secret_access",
    "execute_doc_commands",
    "install_dependencies",
    "deploy",
    "push",
    "commit",
    "rewrite_history",
    "git_config",
    "modify_gate_state",
    "modify_events"
  ],
  "forbidden_paths": [
    "docs/",
    "linux-docx/",
    "README.md",
    "contracts/",
    "run/events.ndjson",
    "run/plans/",
    "run/tasks/",
    ".claude/",
    "inspect.sh",
    "inspect/__init__.py",
    "inspect/cli.py",
    "inspect/metrics.py",
    "inspect/config.py",
    "inspect/inventory.py",
    "inspect/ansible_runner.py",
    "inspect/probe.py",
    "inspect/normalize.py",
    "inspect/fact_source.py",
    "inspect/schema/",
    "inspect/data/",
    "inspect/templates/",
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/test_cli.py",
    "tests/test_metrics.py",
    "tests/test_config.py",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-105:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/reporting-roadmap.md",
      "sha256": "359ddd6cb7f7e04ec1f00d511143e65532318ede3d14a1f4bc0ce1e9a83aa171",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/host-result-v1.md",
      "sha256": "fb101b1c0bc21371bc08e27f7a7c32a3d130cbf0efc9a1c2c2ca1aa9ad44ba1f",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/technical-design.md",
      "sha256": "e13489e269ee6e2d3f096dffc336f8713ad4b476d1e565e4126fd87c1d119e3f",
      "version": "G2-approved"
    },
    {
      "path": "docs/specs/task-dag.md",
      "sha256": "21c3ea8eeac223823b0c0a2c9a08d700e4484752750f6d5f5e81ed76d10669d3",
      "version": "G2-approved"
    },
    {
      "path": "run/tasks/run-20260814-001.json",
      "sha256": "frozen-dag",
      "version": "frozen"
    },
    {
      "path": "inspect/fact_source.py",
      "sha256": "T-104-integrated",
      "version": "T-104-integrated"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "渲染只读 JSON，mock 断言零采集调用",
    "UNKNOWN/ERROR 显式展示原因",
    "无颜色环境符号区分",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "采集/归一化（T-103/T-104 已交付）",
    "Excel/HTML 渲染（T-106/T-107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标"
  ],
  "objective": "实现 stdout 终端渲染器 inspect/render_stdout.py：run 摘要、主机摘要（execution_status 与四状态计数）、失败/未知指标列表（UNKNOWN/ERROR 显式原因）、退出码说明；无颜色环境以符号/缩写区分；只读消费 JSON 不触发采集。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/render_stdout.py",
    "tests/test_render_stdout.py",
    "tests/fixtures/stdout/",
    "run/reports/T-105.md"
  ],
  "parent_task_id": "T-104",
  "phase": "implement",
  "risk_level": "low",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "Excel（T-106）、HTML（T-107）、e2e（T-108）",
      "修改已交付 T-101..T-104 文件",
      "访问任何目标主机、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect/render_stdout.py：从 host-result-v1 JSON 渲染终端输出（run 摘要、主机摘要、失败/未知列表含原因 missing/conflict/permission/timeout、退出码说明、四状态 OK/WARN/CRIT/UNKNOWN 映射、无颜色环境符号区分）",
      "tests/test_render_stdout.py、tests/fixtures/stdout/",
      "run/reports/T-105.md 任务报告"
    ]
  },
  "success_definition": "T-105 合同 AC-1..AC-5 全部通过；只写 owned_paths；受保护路径零改动；任务报告完整；渲染不触发任何采集（mock 断言零执行调用）。",
  "task_id": "T-105",
  "timeout_minutes": 60,
  "triggers": [
    "RR §2 输出约定与实现不一致",
    "需要修改已交付文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": false,
  "worktree": null
}

```

# T-105 stdout 渲染 实现合同 v1

## 目标

实现 stdout 终端渲染器。渲染层只读消费 host-result-v1 JSON，绝不触发采集（RR §1 数据流）。

## 必需步骤

1. 只读阅读 docs/specs/reporting-roadmap.md §2（stdout 输出约定）、§5（四状态与颜色）、docs/specs/host-result-v1.md §8（与报表的关系）、docs/specs/technical-design.md §8、docs/specs/task-dag.md §8。
2. 实现 inspect/render_stdout.py：run 摘要、主机摘要（execution_status 徽标 + 四状态计数）、失败/未知指标列表（UNKNOWN/ERROR 显式原因 missing/conflict/permission/timeout）、退出码说明；无颜色环境（NO_COLOR/非 TTY）用符号/缩写区分；`execution_status != SUCCESS` 时必须展示技术失败计数不掩盖（HR §8）。
3. 测试与夹具：tests/test_render_stdout.py（状态计数与 JSON 一致、UNKNOWN/ERROR 原因展示、无颜色符号、渲染零采集 mock 断言）、tests/fixtures/stdout/（用 T-104 fixtures/json/ 同类样例 JSON）。
4. 运行 AC-1..AC-2，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-105.md；报告含文件清单与 sha256、结构审查、受保护路径 git diff 验证。
5. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成。

## 停止规则

发现与 RR §2 输出约定冲突、需要修改 owned_paths 之外文件、AC 与冻结 DAG 不一致 → 立即停止报告。不得实现 T-106/T-107/T-108 范围功能、不得把占位当完成。
