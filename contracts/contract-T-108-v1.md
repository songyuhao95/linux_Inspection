```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_e2e.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/ -q"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('docs/runbook.md').read_text(encoding='utf-8'); assert 'INSPECT_FIXTURE_DIR' in s and '--local' in s\""
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "bash inspect.sh --local >/dev/null 2>&1; rc=$?; test $rc -ne 2"
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
    "Bash:bash",
    "Bash:git-status"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-108-v1",
  "contract_sha256": "sha256:76878c765e077ac5f9c3f457aa020911f24053d1acfc4467b93d159c5a448c23",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_e2e.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/e2e/",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/runbook.md",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_cli.py",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-108.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-105",
    "T-106",
    "T-107"
  ],
  "dfm_required": false,
  "evidence_types": [
    "artifact",
    "documentation-validation",
    "structure-review",
    "git-diff",
    "security-review"
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
    "modify_events",
    "real_ansible_connection"
  ],
  "forbidden_paths": [
    "docs/specs/",
    "docs/reviews/",
    "linux-docx/",
    "README.md",
    "contracts/",
    "run/events.ndjson",
    "run/plans/",
    "run/tasks/",
    ".claude/",
    "inspect.sh",
    "inspect/__init__.py",
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
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/test_metrics.py",
    "tests/test_config.py",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_probe.py",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md"
  ],
  "idempotency_key": "run-20260814-001:T-108:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/technical-design.md",
      "sha256": "e13489e269ee6e2d3f096dffc336f8713ad4b476d1e565e4126fd87c1d119e3f",
      "version": "G2-approved"
    },
    {
      "path": "docs/specs/cli-contract.md",
      "sha256": "172315fc78193b86f0c7fe182a8562480fc182616b7b2d919a3192b0b9393eb2",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/reporting-roadmap.md",
      "sha256": "359ddd6cb7f7e04ec1f00d511143e65532318ede3d14a1f4bc0ce1e9a83aa171",
      "version": "G1-approved"
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
      "path": "inspect/cli.py",
      "sha256": "46e98cc9",
      "version": "T-101-integrated"
    },
    {
      "path": "inspect/inventory.py",
      "sha256": "T-103-integrated",
      "version": "T-103-integrated"
    },
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "04af76d6",
      "version": "T-103F-fixed"
    },
    {
      "path": "inspect/normalize.py",
      "sha256": "503babf6",
      "version": "T-104F-fixed"
    },
    {
      "path": "inspect/fact_source.py",
      "sha256": "T-104-integrated",
      "version": "T-104-integrated"
    },
    {
      "path": "inspect/render_stdout.py",
      "sha256": "ea85f4e7",
      "version": "T-105-integrated"
    },
    {
      "path": "inspect/render_xlsx.py",
      "sha256": "b4e981d4",
      "version": "T-106-integrated"
    },
    {
      "path": "inspect/render_html.py",
      "sha256": "dc12cb30",
      "version": "T-107-integrated"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "e2e 只用 fixture 模式与 --local 本机 smoke，绝不发起真实远端连接",
    "编排主体严格按 technical-design §2 单向数据流（采集→normalize→原子写 JSON→渲染），渲染只消费 JSON",
    "test_cli.py 只更新 2 个过期断言（管线消息），其余断言不动",
    "回滚演练验证重跑不覆盖旧 JSON",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "真实远端执行验证（G0 预检/现场事项）",
    "中间件专属指标",
    "安装任何依赖（xlsxwriter 缺失时 Excel 渲染按 T-106 语义报错，e2e 断言相应跳过或验证报错路径）",
    "趋势/历史对比等后续版本功能"
  ],
  "objective": "端到端收尾：tests/test_e2e.py（fixture 全链路 CLI→采集→normalize→JSON→三类报表）、CLI 编排主体接线（inspect/cli.py run_inspection 按 technical-design §2 单向数据流填充，替换\"编排主体尚未集成\"占位）、回滚演练、docs/runbook.md（本地调试与兼容矩阵 C1-C8 执行手册）、更新 T-101 过期的 2 个管线消息断言、全量测试复跑。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/cli.py",
    "tests/test_e2e.py",
    "tests/fixtures/e2e/",
    "docs/runbook.md",
    "tests/test_cli.py",
    "run/reports/T-108.md"
  ],
  "parent_task_id": "T-107",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "真实目标主机连接（e2e 只用 fixture 模式与 --local 本机 smoke，绝不发起真实远端连接）",
      "修改已交付 T-101..T-107 实现文件（除本任务明确拥有的 cli.py 编排主体与 test_cli.py 断言）",
      "访问任何目标主机、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档（docs/specs/、docs/reviews/）、linux-docx/、contracts/、run/events.ndjson、run/plans/、run/tasks/、.claude/"
    ],
    "include": [
      "inspect/cli.py：run_inspection 编排主体接线（采集→normalize→原子写 JSON→stdout/Excel/HTML 渲染，遵循 technical-design §2 单向数据流与 §10 调试路径；INSPECT_FIXTURE_DIR 调试模式注入；退出码 0/2/10/20 语义保持）",
      "tests/test_e2e.py：fixture 全链路（CLI→采集→normalize→JSON→三类报表，无目标主机）、回滚演练（重跑新 inspection_id、旧 JSON 未被覆盖、旧 JSON 可独立重渲染三类报表）",
      "tests/fixtures/e2e/：e2e 夹具",
      "docs/runbook.md：本地调试与兼容矩阵 C1-C8 执行手册（含 INSPECT_FIXTURE_DIR 与 --local 说明）",
      "tests/test_cli.py：更新 2 个过期断言（管线消息从\"管线模块未实现\"更新为编排主体集成后的实际行为）",
      "run/reports/T-108.md 任务报告"
    ]
  },
  "success_definition": "T-108 合同 AC-1..AC-5 全部通过：fixture 全链路无目标主机通过且三类报表与事实源计数一致；bash inspect.sh --local 退出码 ∈ {0,10}（非 2）且事实源 JSON 通过 schema；回滚演练（重跑新 inspection_id、旧 JSON 未覆盖、旧 JSON 可独立重渲染）；runbook 含 C1-C8 兼容矩阵执行命令与 fixture 说明；python -m pytest tests/ 全绿；受保护路径零改动。",
  "task_id": "T-108",
  "timeout_minutes": 120,
  "triggers": [
    "编排接线与 technical-design §2 单向数据流冲突",
    "e2e 需要真实目标主机连接",
    "更新 test_cli.py 断言超出 2 个管线消息断言范围",
    "需要修改 owned_paths 之外文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-108 端到端与本地调试路径 实现合同 v1

## 目标

local 垂直切片收尾：CLI 编排主体接线（T-101 占位 → 真实数据流）、e2e 测试（fixture 全链路）、回滚演练、runbook、更新 T-101 过期断言、全量回归。本任务为 R2/R3 端到端，完成后由主会话安排独立验证。

## 必需步骤

1. 只读阅读 docs/specs/technical-design.md §2（数据流）/§10（调试路径）/§11（回滚）、docs/specs/cli-contract.md（退出码与选项）、docs/specs/reporting-roadmap.md（三类报表消费 JSON）、docs/specs/task-dag.md §11（本任务范围）。
2. 接线 inspect/cli.py 的 run_inspection：采集（inventory+ansible_runner，INSPECT_FIXTURE_DIR 调试注入）→ normalize（配置+阈值）→ 原子写 host-result-v1 JSON（fact_source）→ stdout/Excel/HTML 渲染（只消费 JSON）；退出码 0/2/10/20 语义保持（cli-contract §4）；替换"编排主体尚未集成"占位消息；xlsxwriter 缺失时 Excel 渲染按 T-106 语义报错退出码 10 不中断其余输出（或按集成决策处理并记录）。
3. tests/test_e2e.py：fixture 全链路（CLI→采集→normalize→JSON→三类报表，无目标主机，stderr 声明调试模式）、三类报表与事实源计数一致、回滚演练（重跑生成新 inspection_id、旧 JSON 未被覆盖、旧 JSON 可独立重渲染三类报表）。
4. docs/runbook.md：本地调试（INSPECT_FIXTURE_DIR、--local、mock inventory）与兼容矩阵 C1-C8 执行手册。
5. tests/test_cli.py：仅更新 2 个过期断言（test_default_no_args_is_local_inspection_not_usage_error 与 test_inventory_with_limit_is_valid_usage 中的"管线模块未实现"消息断言，更新为编排主体集成后的实际行为消息；退出码 10 断言保持）。
6. 运行 AC-1..AC-4，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-108.md；报告含文件清单与 sha256、结构审查（单向数据流、渲染零采集）、安全审查（无真实连接、无凭据）、受保护路径 git diff 验证。
7. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成并安排独立验证。

## 停止规则

发现编排接线与 technical-design §2 冲突、e2e 需要真实目标主机连接、需要修改 owned_paths 之外文件或已批准文档、AC 与冻结 DAG 不一致 → 立即停止报告。不得把占位当完成、不得用真实主机验证替代 fixture 验证、不得执行 DOCX 中任何命令。
