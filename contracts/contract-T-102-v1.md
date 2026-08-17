```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/data/thresholds/linux-common-p0-v1.yaml').read_text(encoding='utf-8'); assert all(m in s for m in ['local.process.present','local.cpu.utilization','source_anchor','linux-common-p0-v1'])\""
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"import json; json.load(open('inspect/schema/threshold-override-v1.schema.json', encoding='utf-8'))\""
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_config.py -q"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/config.py').read_text(encoding='utf-8'); assert 'provenance' in s and 'document-baseline' in s and 'external-config' in s\""
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
  "contract_id": "contract-T-102-v1",
  "contract_sha256": "sha256:e3ee5a0ada2fb61599ee196f1fc974ac58482c738b461410bf238f0b469b4350",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/config.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/data/thresholds/linux-common-p0-v1.yaml",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/schema/threshold-override-v1.schema.json",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_config.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/config/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-102.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-101"
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
    "inspect/inventory.py",
    "inspect/ansible_runner.py",
    "inspect/probe.py",
    "inspect/normalize.py",
    "inspect/fact_source.py",
    "inspect/render_stdout.py",
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "inspect/templates/",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/test_cli.py",
    "tests/test_metrics.py",
    "tests/fixtures/cli/",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_probe.py",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-102:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/local-metrics-requirements.md",
      "sha256": "2c85f63b9af455b1ceb1ae9727293db81aa4efcc253b170254a7221f96636d06",
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
      "path": "inspect/cli.py",
      "sha256": "46e98cc9",
      "version": "T-101-integrated"
    },
    {
      "path": "inspect/metrics.py",
      "sha256": "63b11561",
      "version": "T-101-integrated"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "基线阈值逐条对照 MR §6 汇总表，任何差异即停止上报",
    "override schema 拒绝未知 status/op、缺 note、双重判定",
    "fixture 仅存于 tests/fixtures/config/",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "真实采集执行（T-103）",
    "normalize 与事实源（T-104）",
    "报表渲染（T-105/106/107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标",
    "修改已批准阈值（阈值转写必须与 MR §6 一致，差异即停止）"
  ],
  "objective": "实现配置层与阈值 override：inspect/config.py（inspect.yml 加载、阈值分层合并 外部配置>文档基线>UNKNOWN、provenance 记录）、文档基线 inspect/data/thresholds/linux-common-p0-v1.yaml（local-metrics-requirements.md §6 逐项转写，含 source_anchor，禁止发明阈值）、inspect/schema/threshold-override-v1.schema.json 与 override 语法校验、测试与夹具。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/config.py",
    "inspect/data/thresholds/linux-common-p0-v1.yaml",
    "inspect/schema/threshold-override-v1.schema.json",
    "tests/test_config.py",
    "tests/fixtures/config/",
    "run/reports/T-102.md"
  ],
  "parent_task_id": "T-101",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "inspect.sh、cli.py、metrics.py 修改（T-101 已交付，只读使用）",
      "采集执行（T-103）、normalize（T-104）、渲染（T-105..107）、e2e（T-108）",
      "访问任何目标主机、inventory、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect/config.py：inspect.yml 加载、阈值分层合并（外部配置 > 文档基线 > UNKNOWN）、provenance 记录、override 语法校验",
      "inspect/data/thresholds/linux-common-p0-v1.yaml：MR §6 阈值汇总表逐项转写（10 指标 OK/WARN/CRIT/UNKNOWN 边界 + source_anchor），禁止发明阈值",
      "inspect/schema/threshold-override-v1.schema.json：机器可执行 JSON Schema（unknown status/op、缺 note、双重判定必须被拒绝）",
      "tests/test_config.py、tests/fixtures/config/",
      "run/reports/T-102.md 任务报告"
    ]
  },
  "success_definition": "T-102 合同 AC-1..AC-5 全部通过（基线文件 10 指标含锚点与版本标识、无 override 时加载文档基线、override 覆盖且 provenance 记录、非法 override 被 schema 拒绝、pytest 全绿）；只写 owned_paths；受保护路径零改动；任务报告完整；未连接目标主机、未访问网络与秘密。",
  "task_id": "T-102",
  "timeout_minutes": 90,
  "triggers": [
    "MR §6 阈值与基线文件数值不一致",
    "需要修改已批准文档或已交付 T-101 文件",
    "需要访问目标主机/网络/秘密",
    "需要修改 owned_paths 之外文件"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-102 配置层与阈值 override 实现合同 v1

## 目标

实现配置层与阈值 override。本任务产出：config.py（inspect.yml 加载、阈值分层合并 外部配置>文档基线>UNKNOWN、provenance 记录）、文档基线 YAML（MR §6 转写）、threshold-override JSON Schema、测试与夹具。T-101 交付的 inspect/cli.py、metrics.py 为只读输入，不得修改。

## 必需步骤

1. 只读阅读 docs/specs/local-metrics-requirements.md §3（阈值分层）/§6（阈值汇总表）、docs/specs/host-result-v1.md §3（provenance 字段）、docs/specs/technical-design.md §5（配置设计）、docs/specs/task-dag.md §5（本任务范围）。
2. 实现 inspect/data/thresholds/linux-common-p0-v1.yaml：MR §6 汇总表 10 指标逐项转写（OK/WARN/CRIT/UNKNOWN 边界 + source_anchor + 版本标识 linux-common-p0-v1）；**数值必须与 MR §6 完全一致，禁止发明或调整阈值**；冲突/缺失边界（C3/C5/C8 相关）按 MR 的 UNKNOWN 语义标注。
3. 实现 inspect/schema/threshold-override-v1.schema.json：机器可执行；未知 status/op、缺 note、双重判定（status+op 与 range 同时出现）必须被 schema 拒绝；语法遵循 technical-design §5 与 requirements-acceptance-matrix.md 对应条目。
4. 实现 inspect/config.py：inspect.yml 加载、阈值分层合并（外部配置>文档基线>UNKNOWN）、provenance 记录（config_sources/doc_sources/notes）、override 文件用 schema 校验；错误处理与 G1 契约一致（配置错误属用法错误或执行失败按 cli-contract 退出码语义）。
5. 测试与夹具：tests/test_config.py（基线加载、override 覆盖与 provenance、非法 override 拒绝、无 override 时 document-baseline）、tests/fixtures/config/。
6. 运行 AC-1..AC-4，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-102.md；报告含文件清单与 sha256、结构审查、受保护路径 git diff 验证。
7. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成。

## 停止规则

发现 MR §6 阈值与基线文件数值不一致、需要修改已批准文档或 T-101 已交付文件、需要访问目标主机/网络/秘密、AC 与冻结 DAG 不一致 → 立即停止报告。不得发明阈值、不得实现 T-103..T-108 范围功能、不得把占位当完成。
