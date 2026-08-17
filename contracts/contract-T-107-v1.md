```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_render_html.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/templates/html-report-v1.html').read_text(encoding='utf-8'); assert '<link' not in s and '<script src' not in s\""
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
  "contract_id": "contract-T-107-v1",
  "contract_sha256": "sha256:650f1e2fa79556a34b5e05c1900f2644259b207e15dc39bcfff7ad51bb5af8fb",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_html.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/templates/html-report-v1.html",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_render_html.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/html/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-107.md",
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
    "inspect/render_stdout.py",
    "inspect/render_xlsx.py",
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
    "tests/test_render_xlsx.py",
    "tests/test_e2e.py",
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-107:v1",
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
    "模板零外链（无 <link、无 <script src、无 fetch）由 AC-2 机械断言",
    "JSON 内嵌只读，展示层不二次计算",
    "不可信文本（日志片段/证据）HTML 转义",
    "色板常量与 RR §5 一致",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "采集/归一化（T-103/T-104 已交付）",
    "stdout/Excel 渲染（T-105/T-106）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标",
    "趋势/历史对比、CSV 导出、自定义色板（路线图后续版本）"
  ],
  "objective": "实现离线单文件 HTML 渲染器 inspect/render_html.py 与模板 inspect/templates/html-report-v1.html：全内联 CSS/JS 零外链、JSON 内嵌、左侧导航+右侧滚动区、宏观卡片（主机数/状态计数/告警/UNKNOWN）+主机详情、四状态色板（#2E7D32/#F9A825/#C62828/#757575）、按状态/主机/指标过滤、打印友好默认宏观摘要、HTML 转义不可信文本。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/render_html.py",
    "inspect/templates/html-report-v1.html",
    "tests/test_render_html.py",
    "tests/fixtures/html/",
    "run/reports/T-107.md"
  ],
  "parent_task_id": "T-104",
  "phase": "implement",
  "risk_level": "low",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "stdout（T-105）、Excel（T-106）、e2e（T-108）",
      "修改已交付 T-101..T-104 文件",
      "访问任何目标主机、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect/render_html.py：JSON 内嵌渲染（数据只读，展示层不做二次计算）、HTML 转义（不可信文本如日志片段/证据必须转义）、文件名 <inspection-id>.html 且 --html-out 可覆盖（函数参数语义）",
      "inspect/templates/html-report-v1.html：全内联 CSS/JS 零外链、左导航（run 摘要/主机列表/状态筛选 OK/WARN/CRIT/UNKNOWN/指标维度）+右滚动区（宏观卡片→主机详情逐指标卡片 raw/normalized/unit/status/threshold/evidence/error/provenance）、四状态色板 RR §5、打印友好默认宏观摘要、状态/主机/指标过滤交互",
      "tests/test_render_html.py、tests/fixtures/html/",
      "run/reports/T-107.md 任务报告"
    ]
  },
  "success_definition": "T-107 合同 AC-1..AC-5 全部通过；只写 owned_paths；受保护路径零改动；任务报告完整；生成文件为离线单文件（无 <link、无 <script src、无 fetch/外链）。",
  "task_id": "T-107",
  "timeout_minutes": 90,
  "triggers": [
    "RR §4/§5 布局/色板与实现不一致",
    "模板出现外链资源",
    "需要修改已交付文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": false,
  "worktree": null
}

```

# T-107 离线单文件 HTML 渲染 实现合同 v1

## 目标

实现离线单文件 HTML 渲染器与模板。渲染层只读消费 host-result-v1 JSON，绝不触发采集；生成文件离线可用（无 CDN/服务端依赖）。

## 必需步骤

1. 只读阅读 docs/specs/reporting-roadmap.md §4（HTML 布局）/§5（色板与徽标）、docs/specs/host-result-v1.md §8、docs/specs/technical-design.md §8、docs/specs/task-dag.md §10。
2. 实现 inspect/templates/html-report-v1.html：全内联 CSS/JS（无 <link、无 <script src、无 fetch/外链）、左导航（run 摘要/主机列表/状态筛选 OK/WARN/CRIT/UNKNOWN/指标维度）+右滚动区（宏观卡片→主机详情逐指标卡片）、四状态色板常量 #2E7D32/#F9A825/#C62828/#757575、打印友好（默认宏观摘要，详情可展开）、按状态/主机/指标过滤交互、JSON 内嵌（只读展示不二次计算）、不可信文本（日志片段/evidence/error message）HTML 转义。
3. 实现 inspect/render_html.py：渲染入口（JSON→HTML 文件）、文件名 <inspection-id>.html 与 --html-out 覆盖（函数参数语义）、转义保证（测试断言 <script> 注入/HTML 特殊字符被转义）。
4. 测试与夹具：tests/test_render_html.py（单文件断言、内嵌 JSON 与事实源一致、四状态过滤可用、色板/徽标断言、打印友好、转义断言）、tests/fixtures/html/。
5. 运行 AC-1..AC-2，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-107.md；报告含文件清单与 sha256、结构审查、受保护路径 git diff 验证。
6. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成。

## 停止规则

发现与 RR §4/§5 布局或色板冲突、模板出现外链资源、需要修改 owned_paths 之外文件、AC 与冻结 DAG 不一致 → 立即停止报告。不得实现 T-105/T-106/T-108 范围功能、不得把占位当完成。
