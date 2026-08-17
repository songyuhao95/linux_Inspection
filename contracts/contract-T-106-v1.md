```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_render_xlsx.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/render_xlsx.py').read_text(encoding='utf-8'); assert 'xlsxwriter' in s and 'Overview' in s and 'Errors-Evidence' in s\""
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
  "contract_id": "contract-T-106-v1",
  "contract_sha256": "sha256:5dba1bd57d05beb6544601f7ea0674627c5d922a15b46ff143ffb92aa2c5e203",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_xlsx.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_render_xlsx.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/xlsx/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-106.md",
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
    "inspect/render_stdout.py",
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
    "tests/test_render_stdout.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-106:v1",
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
    "渲染只读 JSON",
    "xlsxwriter 缺失时明确报错退出码 10（负向测试）",
    "CRIT 值红色样式、UNKNOWN 不混入 OK 计数",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "采集/归一化（T-103/T-104 已交付）",
    "stdout/HTML 渲染（T-105/T-107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标",
    "安装任何依赖"
  ],
  "objective": "实现 Excel 渲染器 inspect/render_xlsx.py（xlsxwriter）：三 Sheet Overview/Local/Errors-Evidence，布局遵循 reporting-roadmap.md §3；UNKNOWN 不混入 OK 计数；文件名 <inspection-id>.xlsx 且 --xlsx-out 可覆盖；xlsxwriter 缺失时明确报错退出码 10；CRIT 值红色样式。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/render_xlsx.py",
    "tests/test_render_xlsx.py",
    "tests/fixtures/xlsx/",
    "run/reports/T-106.md"
  ],
  "parent_task_id": "T-104",
  "phase": "implement",
  "risk_level": "low",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "stdout（T-105）、HTML（T-107）、e2e（T-108）",
      "修改已交付 T-101..T-104 文件",
      "访问任何目标主机、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/",
      "安装 xlsxwriter（requirements.txt 已声明；本任务不安装，缺失时实现明确报错路径与测试 skip 策略）"
    ],
    "include": [
      "inspect/render_xlsx.py：xlsxwriter 实现三 Sheet（Overview run 信息/主机×状态汇总/状态计数/阈值版本/生成时间；Local 每主机每指标一行 metric_id/raw/normalized/unit/status/threshold 规则/来源锚点/evidence 摘要/provenance；Errors-Evidence 所有 error 非空指标与主机 error.code/message/command/output_summary 与 UNKNOWN 清单），四状态样式（OK 绿/WARN 橙/CRIT 红/UNKNOWN 灰），CRIT 值红色字体，UNKNOWN 不混入 OK 计数",
      "tests/test_render_xlsx.py、tests/fixtures/xlsx/",
      "run/reports/T-106.md 任务报告"
    ]
  },
  "success_definition": "T-106 合同 AC-1..AC-5 全部通过；只写 owned_paths；受保护路径零改动；任务报告完整；渲染只读消费 JSON。",
  "task_id": "T-106",
  "timeout_minutes": 60,
  "triggers": [
    "RR §3 布局与实现不一致",
    "需要修改已交付文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": false,
  "worktree": null
}

```

# T-106 Excel 渲染 实现合同 v1

## 目标

实现 Excel 渲染器（xlsxwriter，三 Sheet）。渲染层只读消费 host-result-v1 JSON，绝不触发采集（RR §1 数据流）。xlsxwriter 为 requirements.txt 已声明依赖但本任务不安装：实现 import 缺失时的明确报错路径（退出码 10 语义），测试在缺失环境下 skip 渲染断言但保留模块级常量与契约断言。

## 必需步骤

1. 只读阅读 docs/specs/reporting-roadmap.md §3（Excel 布局）/§5（四状态色板）、docs/specs/host-result-v1.md §8、docs/specs/technical-design.md §8、docs/specs/task-dag.md §9。
2. 实现 inspect/render_xlsx.py：三 Sheet Overview/Local/Errors-Evidence（列与内容按 RR §3 表格）；状态文字+背景色（OK #2E7D32/WARN #F9A825/CRIT #C62828/UNKNOWN #757575），CRIT 值红色字体（用户需求：达到告警阈值的值红色字体）；UNKNOWN 不混入 OK 计数；文件名 <inspection-id>.xlsx 且 --xlsx-out 可覆盖（函数参数语义，CLI 接线在集成阶段）；xlsxwriter import 缺失→明确报错（RendererError 语义对应退出码 10）。
3. 测试与夹具：tests/test_render_xlsx.py（三 Sheet 存在且内容符合 RR §3、状态计数与 JSON 一致、UNKNOWN 不混入 OK、xlsxwriter 缺失负向测试、CRIT 样式断言——若 xlsxwriter 缺失则用模块级常量/结构断言+skip 实际渲染）、tests/fixtures/xlsx/。
4. 运行 AC-1..AC-2，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-106.md；报告含文件清单与 sha256、结构审查、受保护路径 git diff 验证。
5. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成。

## 停止规则

发现与 RR §3 布局冲突、需要修改 owned_paths 之外文件、AC 与冻结 DAG 不一致 → 立即停止报告。不得实现 T-105/T-107/T-108 范围功能、不得把占位当完成。
