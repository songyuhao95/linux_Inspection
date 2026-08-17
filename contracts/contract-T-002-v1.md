```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; ps=[Path(p) for p in ['docs/specs/requirements-acceptance-matrix.md','docs/specs/technical-design.md','docs/specs/risk-register.md','docs/specs/task-dag.md','docs/reviews/plan-review.md','run/plans/run-20260814-001-plan.json']]; assert all(p.is_file() and p.stat().st_size>1000 for p in ps)\""
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('docs/specs/requirements-acceptance-matrix.md').read_text(encoding='utf-8'); req=['local.process.present','local.cpu.utilization','host-result-v1','cli-contract','ansible-execution','reporting-roadmap']; assert all(x in s for x in req)\""
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('docs/specs/technical-design.md').read_text(encoding='utf-8'); req=['inspect.sh','probe','raw','script','JSON','xlsx','html','threshold','inventory']; assert all(x in s for x in req)\""
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('docs/specs/task-dag.md').read_text(encoding='utf-8'); req=['T-101','T-102','T-103','T-104','T-105','T-106','T-107','T-108']; assert all(x in s for x in req)\""
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "git diff --exit-code -- docs/specs docs/reviews/docx-source-conflicts.md linux-docx README.md contracts/ run/events.ndjson"
    }
  ],
  "allowed_tools": [
    "Read",
    "Glob",
    "Grep",
    "Write:owned_paths",
    "Edit:owned_paths",
    "Bash:documentation-validation",
    "Bash:git-status"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-002-v1",
  "contract_sha256": "sha256:bd4f2237e06af17287d5279a0449e8b2af9111b57ea5ff2e8255eb3897d43888",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "requirements-matrix",
      "path": "docs/specs/requirements-acceptance-matrix.md",
      "required": true
    },
    {
      "kind": "technical-design",
      "path": "docs/specs/technical-design.md",
      "required": true
    },
    {
      "kind": "risk-register",
      "path": "docs/specs/risk-register.md",
      "required": true
    },
    {
      "kind": "task-dag-doc",
      "path": "docs/specs/task-dag.md",
      "required": true
    },
    {
      "kind": "plan-review",
      "path": "docs/reviews/plan-review.md",
      "required": true
    },
    {
      "kind": "dag-json",
      "path": "run/plans/run-20260814-001-plan.json",
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
    "write_code",
    "decide_scope",
    "network_access",
    "target_host_access",
    "execute_doc_commands",
    "secret_access",
    "install_dependencies",
    "deploy",
    "push",
    "commit",
    "rewrite_history",
    "git_config",
    "modify_gate_state",
    "modify_events",
    "freeze_dag"
  ],
  "forbidden_paths": [
    "docs/specs/inspection-product-brief.md",
    "docs/specs/local-metrics-requirements.md",
    "docs/specs/host-result-v1.md",
    "docs/specs/cli-contract.md",
    "docs/specs/ansible-execution.md",
    "docs/specs/reporting-roadmap.md",
    "docs/reviews/docx-source-conflicts.md",
    "linux-docx/",
    "README.md",
    "contracts/",
    "run/events.ndjson",
    ".claude/"
  ],
  "idempotency_key": "run-20260814-001:T-002:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/inspection-product-brief.md",
      "sha256": "0770f832e4f061886bbea0b94d438dd4cdc92bb8b3833cbba452440d8df6a68f",
      "version": "G1-approved"
    },
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
      "path": "docs/specs/cli-contract.md",
      "sha256": "172315fc78193b86f0c7fe182a8562480fc182616b7b2d919a3192b0b9393eb2",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/ansible-execution.md",
      "sha256": "3dc03751cec2ad3491903737553cdf5a7c49115d0101d6f368b917c68128e070",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/reporting-roadmap.md",
      "sha256": "359ddd6cb7f7e04ec1f00d511143e65532318ede3d14a1f4bc0ce1e9a83aa171",
      "version": "G1-approved"
    },
    {
      "path": "docs/reviews/docx-source-conflicts.md",
      "sha256": "fdedac809373300bbe174ac2232c5bbd4b3aa5669ea9077811ba0b79d19cb844",
      "version": "G1-approved"
    }
  ],
  "manual_gate_required": true,
  "max_attempts": 2,
  "mitigations": [
    "只读分析 G1 文档，冲突立即停止上报",
    "DAG 写范围互斥（每任务独立目录与文件）",
    "所有主机/路径/凭据保持配置边界",
    "方案文档不含实现代码",
    "plan.json 由主会话 freeze，本任务不自行冻结"
  ],
  "network_scope": [],
  "non_goals": [
    "实现或运行巡检代码",
    "生成真实 Excel/HTML 报表",
    "中间件专属指标实现",
    "替用户批准 G2",
    "发明阈值或承诺未验证的系统版本"
  ],
  "objective": "依据已批准 G0/G1 文档（G1 已批准，产品简档 0770f832...），产出 local 垂直切片的 G2 技术方案、需求/验收矩阵、风险登记与垂直任务 DAG，供主会话 tasks.mjs freeze 与用户 G2 批准。",
  "output_schema": "task-report",
  "owned_paths": [
    "docs/specs/requirements-acceptance-matrix.md",
    "docs/specs/technical-design.md",
    "docs/specs/risk-register.md",
    "docs/specs/task-dag.md",
    "docs/reviews/plan-review.md",
    "run/plans/run-20260814-001-plan.json"
  ],
  "parent_task_id": null,
  "phase": "plan",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "写 Shell/Python/Ansible/Excel/HTML 实现代码",
      "访问任何目标主机、inventory、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改 docs/specs/*.md、docs/reviews/*.md、linux-docx/、README.md、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "只读分析 docs/specs/*.md、docs/reviews/docx-source-conflicts.md、run/reports/T-001.md、run/events.ndjson（G1 批准记录）",
      "将 G1 文档转写为 G2 技术方案与任务 DAG",
      "明确本地调试路径（无目标主机时的模拟/inventory 配置边界）",
      "定义报表渲染、JSON 事实源、CLI 解析与 Ansible 执行的模块边界"
    ]
  },
  "success_definition": "五份方案文档与一份 plan.json 完整、一致、可追溯：需求矩阵每条映射 G1 文档 AC/NFR 与可执行验证方法；技术方案冻结 G2 待定项（目录布局、probe 命令与解析器、阈值 override 语法、JSON Schema、Excel/HTML 库与模板、兼容矩阵、回滚）；任务 DAG 无环、依赖合法、写范围不重叠且每个任务可独立实现测试；tasks.mjs freeze 通过；未写实现代码、未连接目标主机。",
  "task_id": "T-002",
  "timeout_minutes": 90,
  "triggers": [
    "G1 文档与方案不一致",
    "DAG 依赖环或写范围重叠",
    "需要现场主机/凭据验证",
    "需要写实现代码",
    "需要修改已批准 G1 文档"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-002 G2 方案合同 v1

## 目标

基于已批准 G0/G1 文档（G1 已批准，产品简档 sha256 0770f832...），为 local 垂直切片产出 G2 技术方案：需求/验收矩阵、技术设计、风险登记、任务 DAG 文档与 plan.json（供主会话 freeze）。只设计，不写实现。

## 必需步骤

1. 只读分析 7 份 G1 规格/评审文档，提取需求、AC、NFR、数据契约、CLI 契约、执行契约与报表契约。
2. 需求/验收矩阵：每条需求映射来源（G1 文档章节/指标 ID/AC）、验收方法与可执行验证命令。
3. 技术设计：目录布局、模块边界（CLI 解析/Ansible 执行/normalize/JSON 事实源/渲染器）、probe 命令与解析器、阈值 override 文件语法、机器可执行 JSON Schema、Excel/HTML 库与模板、兼容测试矩阵、回滚与本地调试路径（无目标主机时如何验证）。
4. 风险登记：按质量门禁 R0-R3 分类，记录缓解与负责人。
5. 任务 DAG：垂直任务（每任务可独立实现、测试、合并），任务 ID 建议 T-101..T-108 起；每个任务声明 owned_paths/forbidden_paths 互斥、depends_on、AC 与证据类型；写范围不得重叠。
6. 将 DAG 输出为 run/plans/run-20260814-001-plan.json（结构符合 tasks.mjs freeze 要求：tasks 数组含 id/depends_on/owned_paths/ac_map 等）；本任务不自行 freeze（forbidden_ops: freeze_dag），由主会话执行 tasks.mjs freeze。
7. 运行 AC-1..AC-5 并记录证据；不 commit/push；交付 worktree 路径与文件清单。

## 停止规则

G1 文档冲突、DAG 环或写范围重叠无法机械解决、需要现场主机/凭据、需要写实现代码、需要修改已批准 G1 文档 → 立即停止报告。不得替用户批准 G2、不得发明阈值、不得把建议写成承诺。
