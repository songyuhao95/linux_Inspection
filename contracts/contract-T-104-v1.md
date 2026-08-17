```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_normalize.py -q"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_fact_source.py -q"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -c \"import json; json.load(open('inspect/schema/host-result-v1.schema.json', encoding='utf-8')); s=open('inspect/schema/host-result-v1.schema.json',encoding='utf-8').read(); assert 'execution_status' in s and 'OK' in s and 'WARN' in s and 'CRIT' in s and 'UNKNOWN' in s\""
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('inspect/normalize.py').read_text(encoding='utf-8'); assert 'PERMISSION_DENIED' in s and 'TIMEOUT' in s and 'PARSE_FAILED' in s\""
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
  "contract_id": "contract-T-104-v1",
  "contract_sha256": "sha256:0d6adee36141d88d53c4ab5dcaa72a7bcdfb5d1887934cb68e468122ce81467b",
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
      "path": "inspect/fact_source.py",
      "required": true
    },
    {
      "kind": "implementation",
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
      "path": "tests/test_fact_source.py",
      "required": true
    },
    {
      "kind": "fixture",
      "path": "tests/fixtures/json/",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-104.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-103"
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
    "inspect/data/",
    "inspect/templates/",
    "inspect/render_stdout.py",
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
    "tests/fixtures/cli/",
    "tests/fixtures/config/",
    "tests/fixtures/inventory/",
    "tests/fixtures/raw/",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/stdout/",
    "tests/fixtures/xlsx/",
    "tests/fixtures/html/",
    "tests/fixtures/e2e/",
    "run/reports/T-101.md",
    "run/reports/T-102.md",
    "run/reports/T-103.md",
    "run/reports/T-105.md",
    "run/reports/T-106.md",
    "run/reports/T-107.md",
    "run/reports/T-108.md"
  ],
  "idempotency_key": "run-20260814-001:T-104:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/host-result-v1.md",
      "sha256": "fb101b1c0bc21371bc08e27f7a7c32a3d130cbf0efc9a1c2c2ca1aa9ad44ba1f",
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
    },
    {
      "path": "inspect/metrics.py",
      "sha256": "63b11561",
      "version": "T-101-integrated"
    },
    {
      "path": "inspect/config.py",
      "sha256": "c26dc2e2",
      "version": "T-102-integrated"
    },
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "b21b6d8c",
      "version": "T-103-integrated"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "schema 文件即机器校验真源，测试以 jsonschema 语义校验所有输出（无运行时依赖时用内嵌子集校验器）",
    "脱敏在 normalize 阶段完成，测试断言 IP→<IP>、凭据零出现",
    "原子写 tmp→fsync→rename，写入失败→退出码 10，损坏检测 parse+schema",
    "error 存在→status=UNKNOWN、execution_status=PARTIAL/ERROR，技术失败不得伪装业务 CRIT",
    "C3/C5/C8 冲突/缺失边界→UNKNOWN（layer=unresolved-document-conflict/missing），外部配置覆盖生效"
  ],
  "network_scope": [],
  "non_goals": [
    "真实远端执行验证（G0 预检/现场事项）",
    "报表渲染（T-105/106/107）",
    "端到端与回滚演练（T-108）",
    "中间件专属指标",
    "修改已批准阈值（判定必须遵循 MR §6 与 C1-C13 冲突语义）"
  ],
  "objective": "实现 normalize + host-result-v1 事实源：inspect/normalize.py（10 指标解析器、脱敏、四状态判定、threshold/provenance 填充、执行/业务状态分离）、inspect/fact_source.py（原子写 tmp→fsync→rename、汇总索引、inspection_id 唯一不覆盖）、inspect/schema/host-result-v1.schema.json 落盘、测试与夹具。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/normalize.py",
    "inspect/fact_source.py",
    "inspect/schema/host-result-v1.schema.json",
    "tests/test_normalize.py",
    "tests/test_fact_source.py",
    "tests/fixtures/json/",
    "run/reports/T-104.md"
  ],
  "parent_task_id": "T-103",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "采集执行（T-103 已交付，只读使用）、渲染（T-105..107）、e2e（T-108）",
      "修改已交付 T-101/T-102/T-103 文件",
      "访问任何目标主机、网络服务或秘密",
      "执行 DOCX 中出现的命令",
      "修改任何已批准文档、linux-docx/、contracts/、run/events.ndjson、.claude/"
    ],
    "include": [
      "inspect/normalize.py：10 个 P0 指标解析器（原始输出→metric 对象）、脱敏（IP→<IP>、凭据占位）、四状态判定（外部配置>文档基线>UNKNOWN）、threshold/provenance 填充、error 存在时 status=UNKNOWN 与 execution_status=PARTIAL/ERROR 分离",
      "inspect/fact_source.py：原子写 tmp→fsync→rename、汇总索引、inspection_id 唯一、重跑不覆盖",
      "inspect/schema/host-result-v1.schema.json：机器可执行 JSON Schema（execution_status 枚举、四状态枚举、必填字段），与 host-result-v1.md §3 一致",
      "tests/test_normalize.py、tests/test_fact_source.py、tests/fixtures/json/",
      "run/reports/T-104.md 任务报告"
    ]
  },
  "success_definition": "T-104 合同 AC-1..AC-7 全部通过；只写 owned_paths；受保护路径零改动；任务报告完整；未连接目标主机、未访问网络与秘密；脱敏规则（IP→<IP>、凭据零出现）在测试中可验证。",
  "task_id": "T-104",
  "timeout_minutes": 120,
  "triggers": [
    "host-result-v1.md §3 与 schema/解析器不一致",
    "脱敏规则失效（IP 或凭据出现在输出）",
    "原子写不完整或重跑覆盖",
    "需要修改已交付文件或已批准文档",
    "AC 与冻结 DAG 不一致"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-104 normalize + host-result-v1 事实源 实现合同 v1

## 目标

实现 normalize 与事实源层（R1 持久化 + R3 脱敏风险）。normalize.py 将 T-103 采集的原始输出转成 host-result-v1 契约的 metric 对象（解析/脱敏/四状态判定/threshold/provenance）；fact_source.py 原子写 JSON 事实源；host-result-v1.schema.json 落盘为机器校验真源。

## 必需步骤

1. 只读阅读 docs/specs/host-result-v1.md（顶层结构/execution_status 与业务 status 分离/metric 对象字段/error 结构/状态判定流程/原子写与文件约定/完整示例）、docs/specs/local-metrics-requirements.md §3/§4/§5/§6、docs/specs/technical-design.md §7、docs/specs/task-dag.md §7。
2. 实现 inspect/schema/host-result-v1.schema.json：与 HR §3 字段语义一致（execution_status 枚举 SUCCESS/PARTIAL/ERROR、status 枚举 OK/WARN/CRIT/UNKNOWN、必填字段、error 结构、threshold/provenance 结构）。
3. 实现 inspect/normalize.py：10 个 P0 指标解析器（以 T-103 fixtures/raw/ 预录输出为解析输入基准）、脱敏（IP→<IP>、凭据占位）、四状态判定（外部配置>文档基线>UNKNOWN 顺序，遵循 HR §4 不可变流程）、threshold/provenance 填充、error 存在时 status=UNKNOWN；error code 枚举（CONNECTION_FAILED/TIMEOUT/PERMISSION_DENIED/COMMAND_NOT_FOUND/PARSE_FAILED/DATA_MISSING/PROBE_FAILED/UNSUPPORTED_PROFILE）与 HR §3.2 一致。
4. 实现 inspect/fact_source.py：tmp→fsync→rename 原子写、汇总索引（inspection_id 唯一、重跑不覆盖）、写入失败→退出码 10 语义、损坏文件检测。
5. 测试与夹具：tests/test_normalize.py（10 指标 fixture→metric 对象必填字段齐备、C3/C5/C8→UNKNOWN、外部配置覆盖生效、脱敏断言）、tests/test_fact_source.py（原子写、唯一性、不覆盖、写入失败）、tests/fixtures/json/。
6. 运行 AC-1..AC-4，逐条记录输入/预期/实际退出码/证据/结论到 run/reports/T-104.md；报告含文件清单与 sha256、结构审查、安全审查（脱敏验证）、受保护路径 git diff 验证。
7. 不 commit、不 push、不安装依赖；交付 worktree 路径与修改文件清单，由主会话集成并安排独立验证。

## 停止规则

发现与 host-result-v1.md/技术设计冲突、脱敏规则失效、原子写不完整、需要修改已交付文件或已批准文档、AC 与冻结 DAG 不一致 → 立即停止报告。不得实现 T-105..T-108 范围功能、不得把占位当完成、不得执行 DOCX 中任何命令。
