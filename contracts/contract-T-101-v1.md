```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "bash inspect.sh -h | grep -F '退出码: 0 成功 / 2 用法错误 / 10 执行失败 / 20 业务告警'"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"import subprocess; o=subprocess.run(['bash','inspect.sh','--list-metrics'],capture_output=True,text=True).stdout; assert all(m in o for m in ['local.process.present','local.service.active','local.port.listening','local.cpu.utilization','local.cpu.load_1m','local.memory.available_percent','local.swap.used_percent','local.filesystem.used_percent','local.filesystem.inode_used_percent','local.logs.key_evidence'])\""
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 2,
      "test_command": "bash inspect.sh --bogus >/dev/null 2>&1; test $? -eq 2 && bash inspect.sh --local -H 127.0.0.1 >/dev/null 2>&1; test $? -eq 2"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_cli.py -q"
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_metrics.py -q"
    },
    {
      "ac_id": "AC-6",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/cli.py').read_text(encoding='utf-8'); assert '--fail-on' in s and 'exit' in s\""
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
  "contract_id": "contract-T-101-v1",
  "contract_sha256": "sha256:5bcba237918f0bc2d4fddf53fa62c1d99856deb4d950ea16d9a2e9c9e09b5dc9",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect.sh",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/__init__.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/metrics.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "pyproject.toml",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "requirements.txt",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "requirements-dev.txt",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_cli.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_metrics.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/cli/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-101.md",
      "required": true
    }
  ],
  "depends_on": [],
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
    "inspect/config.py",
    "inspect/inventory.py",
    "inspect/ansible_runner.py",
    "inspect/probe.py",
    "inspect/normalize.py",
    "inspect/fact_source.py",
    "inspect/render_stdout.py",
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "inspect/schema/",
    "inspect/templates/",
    "inspect/data/",
    "tests/test_config.py",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_probe.py",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-101:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/cli-contract.md",
      "sha256": "172315fc78193b86f0c7fe182a8562480fc182616b7b2d919a3192b0b9393eb2",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/local-metrics-requirements.md",
      "sha256": "2c85f63b9af455b1ceb1ae9727293db81aa4efcc253b170254a7221f96636d06",
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
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "以 cli-contract.md 选项表与退出码表为准实现",
    "指标注册表逐条对照 local-metrics-requirements.md §5 来源锚点",
    "fixture 仅存于 tests/fixtures/cli/",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "真实采集执行（T-103）",
    "normalize 与事实源（T-104）",
    "报表渲染（T-105/106/107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标"
  ],
  "objective": "实现 local 垂直切片的 CLI 入口与指标注册表：inspect.sh 入口、inspect/cli.py（argparse、主机选择、退出码 0/2/10/20 映射、编排骨架）、inspect/metrics.py（10 个共同 P0 指标定义表）、包骨架（pyproject/requirements）、测试与夹具。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect.sh",
    "inspect/__init__.py",
    "inspect/cli.py",
    "inspect/metrics.py",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tests/test_cli.py",
    "tests/test_metrics.py",
    "tests/fixtures/cli/",
    "run/reports/T-101.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "config.py、inventory.py、ansible_runner.py、probe.py、normalize.py、fact_source.py、render_*.py 等其余模块（T-102..T-108 范围）",
      "访问任何目标主机、inventory、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect.sh bash 入口（仅定位 python3 与包路径，无业务逻辑）",
      "inspect/cli.py：argparse 解析（-h/--help、-H/--hosts、-i/--inventory、--limit、--local、--all、--list-metrics、--info、-e/--excel、--xlsx-out、--html、--html-out、--fail-on critical）、主机选择语义、退出码 0/2/10/20 映射与优先级、编排骨架（后续任务挂接点）",
      "inspect/metrics.py：10 个共同 P0 指标注册表（metric_id/命令/超时/解析器名/单位/来源锚点/阈值规则 ID 引用），锚定 docs/specs/local-metrics-requirements.md §5",
      "pyproject.toml、requirements.txt（xlsxwriter）、requirements-dev.txt（pytest、jsonschema、openpyxl）",
      "tests/test_cli.py、tests/test_metrics.py、tests/fixtures/cli/",
      "run/reports/T-101.md 任务报告"
    ]
  },
  "success_definition": "T-101 合同 AC-1..AC-6 全部通过（帮助文本、--list-metrics/--info、退出码 2/20/10、pytest 全绿、本机语义）；只写 owned_paths；受保护路径零改动；任务报告完整；未连接目标主机、未访问网络与秘密。",
  "task_id": "T-101",
  "timeout_minutes": 90,
  "triggers": [
    "CLI 契约与 cli-contract.md 冲突",
    "需要修改已批准文档",
    "需要访问目标主机/网络/秘密",
    "需要修改 owned_paths 之外文件"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-101 CLI 入口与指标注册表 实现合同 v1

## 目标

实现 `inspect.sh` 入口、`inspect/cli.py`（argparse、主机选择、退出码映射、编排骨架）、`inspect/metrics.py`（10 个共同 P0 指标注册表）、包骨架与测试。本任务是 local 垂直切片主链第一环，后续任务（T-102..T-108）将挂接在 cli 编排点与指标注册表上。

## 必需步骤

1. 只读阅读 docs/specs/cli-contract.md（选项表/退出码表/帮助约定）、docs/specs/local-metrics-requirements.md §5（10 指标定义）、docs/specs/technical-design.md §2/§3（架构与目录布局）、docs/specs/task-dag.md §4（本任务范围）。
2. 实现 inspect.sh（bash 包装：仅定位 python3 与包路径，`exec python3 -m inspect.cli "$@"`，无业务逻辑）。
3. 实现 inspect/cli.py：完整 argparse 选项集、主机选择语义（无 -H/-i 巡检本机、-H 与 --local/-i 互斥、--limit 仅随 -i、--all）、退出码 0/2/10/20 映射与优先级（2 > 10 > 20 > 0）、--list-metrics/--info 只读输出、未实现中间件参数明确报"不支持"退出码 2；编排骨架只预留后续任务挂接点（如 run_inspection() 调采集→normalize→渲染的流程占位，由 T-103..T-108 填充），不得实现采集/配置/渲染逻辑。
4. 实现 inspect/metrics.py：10 个 P0 指标注册表（metric_id、命令、超时、解析器名、单位、来源锚点、阈值规则 ID），逐条对照 MR §5；`--list-metrics`/`--info` 从注册表输出。
5. 测试与夹具：tests/test_cli.py（帮助文本、主机选择语义、退出码、--list-metrics/--info）、tests/test_metrics.py（注册表完整性：10 个 ID、必填字段非空、来源锚点存在）、tests/fixtures/cli/（供测试用夹具）。
6. 运行 AC-1..AC-6，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-101.md；报告还须含文件清单与 sha256、结构审查（模块边界符合 technical-design §4）、受保护路径 git diff 验证。
7. 不 commit、不 push、不安装依赖（requirements 仅为声明）；交付 worktree 路径与修改文件清单，由主会话集成。

## 停止规则

发现与 cli-contract.md/技术设计冲突、需要修改 owned_paths 之外文件、需要访问目标主机/网络/秘密、AC 与冻结 DAG 不一致 → 立即停止报告。不得实现 T-102..T-108 范围功能、不得把占位当完成、不得绕过退出码优先级。
