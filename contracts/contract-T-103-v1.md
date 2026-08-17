```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/ansible_runner.py').read_text(encoding='utf-8'); assert 'gather_facts' in s and 'serial' in s and 'raw' in s and 'bash -lc' in s\""
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/ansible_runner.py').read_text(encoding='utf-8'); assert 'INSPECT_FIXTURE_DIR' in s\""
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/ansible_runner.py').read_text(encoding='utf-8'); assert 'allow' in s.lower() or 'ALLOW' in s\""
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/probe.py').read_text(encoding='utf-8'); assert 'bash' in s and 'pgrep' in s and 'ss' in s and 'free' in s and 'df' in s\""
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/ansible_runner.py').read_text(encoding='utf-8'); assert 'TIMEOUT' in s and 'UNKNOWN' in s and '300' in s\""
    },
    {
      "ac_id": "AC-6",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/inventory.py').read_text(encoding='utf-8'); assert 'limit' in s and 'hosts' in s\""
    },
    {
      "ac_id": "AC-7",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_inventory.py tests/test_ansible_runner.py -q"
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
  "contract_id": "contract-T-103-v1",
  "contract_sha256": "sha256:a2378abd761cf378a6659bb4530f71be21c23fb3a2ee33ff73e91d321a34736a",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/inventory.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/probe.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_inventory.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_ansible_runner.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/inventory/",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/raw/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-103.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-102"
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
    "inspect/data/",
    "inspect/schema/",
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
    "tests/test_config.py",
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/json/",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-104.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-103:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/ansible-execution.md",
      "sha256": "3dc03751cec2ad3491903737553cdf5a7c49115d0101d6f368b917c68128e070",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/cli-contract.md",
      "sha256": "172315fc78193b86f0c7fe182a8562480fc182616b7b2d919a3192b0b9393eb2",
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
      "path": "docs/specs/risk-register.md",
      "sha256": "8e848cc2f1feae54f95b6b33d07c4784184ec0f9395c387cb8f249a387bdb79c",
      "version": "G2-approved"
    },
    {
      "path": "run/tasks/run-20260814-001.json",
      "sha256": "frozen-dag",
      "version": "frozen"
    },
    {
      "path": "inspect/metrics.py",
      "sha256": "63b11561",
      "version": "T-101-integrated"
    },
    {
      "path": "inspect/config.py",
      "sha256": "b21b6d8c",
      "version": "T-102-integrated"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "本任务绝不发起真实 SSH/Ansible 连接（forbidden_ops: real_ansible_connection），全部行为经 fixture 模式与本地验证",
    "playbook 生成严格遵循 ansible-execution.md：gather_facts:false、serial:1、raw/script+/bin/bash -lc、最小化 become、只读命令 allow-list、超时注入、无重试",
    "fixture 模式 stderr 声明调试模式（REQ-N-08）",
    "连接失败→ERROR 无业务结论、部分失败→PARTIAL（REQ-E-07）",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "真实远端执行验证（G0 预检/现场事项）",
    "normalize 与事实源（T-104）",
    "报表渲染（T-105/106/107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标",
    "安装 ansible 或任何依赖（ansible_runner 只生成 playbook 文本与封装调用，本任务不安装不执行真实 ansible-playbook）"
  ],
  "objective": "实现采集执行层：inspect/inventory.py（-H 生成临时 inventory、-i/--limit/--all 解析）、inspect/ansible_runner.py（playbook 生成与执行封装：gather_facts:false、serial:1、raw/script + /bin/bash -lc、最小化 become、INSPECT_FIXTURE_DIR 调试注入点、结果回传）、inspect/probe.py（能力探测命令与解析）、allow-list 校验、超时注入（probe 15s/指标 10s/日志 15s/单主机 300s）、无重试。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/inventory.py",
    "inspect/ansible_runner.py",
    "inspect/probe.py",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "run/reports/T-103.md"
  ],
  "parent_task_id": "T-102",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "真实连接任何目标主机（本任务只用 fixture 模式与本地验证，绝不发起真实 SSH/Ansible 连接）",
      "normalize（T-104）、渲染（T-105..107）、e2e（T-108）",
      "修改已交付 T-101/T-102 文件",
      "访问任何网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect/inventory.py：-H 生成临时 inventory、-i/--limit/--all 解析、错误语义",
      "inspect/ansible_runner.py：playbook 生成（gather_facts:false、serial:1、raw/script + /bin/bash -lc、最小化 become、只读命令 allow-list、每命令超时注入、无重试）、执行封装与结果回传、INSPECT_FIXTURE_DIR 调试注入点（fixture 模式 stderr 声明调试模式）",
      "inspect/probe.py：能力探测命令集合与解析（bash/pgrep/ss/free/df 等，探测失败→COMMAND_NOT_FOUND→UNKNOWN）",
      "tests/test_inventory.py、tests/test_ansible_runner.py、tests/fixtures/inventory/、tests/fixtures/raw/",
      "run/reports/T-103.md 任务报告"
    ]
  },
  "success_definition": "T-103 合同 AC-1..AC-7 全部通过；只写 owned_paths；受保护路径零改动；任务报告完整（含 fixture 模式与 allow-list 证据）；未连接真实目标主机、未访问网络与秘密；行为全部经由 fixture 模式与本地验证。",
  "task_id": "T-103",
  "timeout_minutes": 120,
  "triggers": [
    "需要真实连接目标主机或网络",
    "需要读取秘密或 inventory 凭据",
    "允许列表之外命令被要求执行",
    "需要修改已交付 T-101/T-102 文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-103 采集执行层 实现合同 v1

## 目标

实现采集执行层：inventory.py、ansible_runner.py、probe.py。本任务为 R2 风险任务（外部执行环境+权限模型），**绝不发起真实目标主机连接**——全部行为经 INSPECT_FIXTURE_DIR fixture 模式与本地验证完成；真实远端验证属于 G0 预检/现场事项，不在本合同。

## 必需步骤

1. 只读阅读 docs/specs/ansible-execution.md（执行模型/能力探测/命令执行与安全/权限模型/失败分类/超时）、docs/specs/technical-design.md §6（采集执行层设计）、docs/specs/task-dag.md §6（本任务范围）、docs/specs/risk-register.md §4（R2 风险与缓解）。
2. 实现 inspect/inventory.py：-H 生成临时 inventory（.runtime/）、-i/--limit/--all 解析、错误语义（inventory 路径不存在/解析失败属配置或执行失败按 cli-contract 退出码语义）。
3. 实现 inspect/ansible_runner.py：playbook 生成（gather_facts:false、serial:1、raw/script + /bin/bash -lc、最小化 become、只读命令 allow-list、每命令超时注入 15s/10s/15s/300s、无重试）、执行封装与结果回传、INSPECT_FIXTURE_DIR 调试注入点（fixture 模式返回预录输出且 stderr 声明调试模式，不调用真实 ansible-playbook）。
4. 实现 inspect/probe.py：能力探测命令集合（bash/pgrep/ss/free/df 等）与解析，探测失败→COMMAND_NOT_FOUND→UNKNOWN。
5. 连接失败→ERROR（无业务结论）、部分失败→PARTIAL 的语义在 ansible_runner 结果分类中实现。
6. 测试与夹具：tests/test_inventory.py、tests/test_ansible_runner.py（fixture 模式、allow-list 拒绝未登记命令、超时注入、失败分类）、tests/fixtures/inventory/、tests/fixtures/raw/（预录输出）。
7. 运行 AC-1..AC-7，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-103.md；报告含文件清单与 sha256、结构审查、安全审查（无凭据、无真实连接、无 DOCX 命令）、受保护路径 git diff 验证。
8. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成并安排独立验证。

## 停止规则

发现需要真实连接目标主机/网络、需要读取秘密或 inventory 凭据、allow-list 之外命令被要求执行、需要修改已交付文件或已批准文档、AC 与冻结 DAG 不一致 → 立即停止报告。不得用真实主机验证替代 fixture 验证、不得把占位当完成、不得执行 DOCX 中任何命令。
