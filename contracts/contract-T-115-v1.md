```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_linux_basic.py tests/test_modules.py tests/test_ansible_runner.py tests/test_render_stdout.py"
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
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:git diff --check"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-115-v1",
  "contract_sha256": "sha256:ad2b977ca6abc74eb36263689a5742dfbd056506cc919f3d2b7e92445624afcc",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "module-selection-api",
      "path": "inspect/modules/registry.py",
      "required": true
    },
    {
      "kind": "default-collection-selection",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "json-backed-chinese-metric-output",
      "path": "inspect/render_stdout.py",
      "required": true
    },
    {
      "kind": "renderer-tests",
      "path": "tests/test_render_stdout.py",
      "required": true
    },
    {
      "kind": "integration-tests",
      "path": "tests/test_linux_basic.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    }
  ],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff",
    "vm-smoke"
  ],
  "forbidden_ops": [
    "network installation",
    "system Ansible fallback",
    "force_push",
    "secret logging",
    "unauthorized hosts",
    "modify protected workflow artifacts"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/"
  ],
  "idempotency_key": "T-115",
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "仅默认收集 profile-free linux_basic；中间件指标只有显式模块选择时进入执行规格。",
    "报告只读取事实源 JSON，不读取采集 stdout 或重新采集。"
  ],
  "network_scope": [],
  "objective": "默认巡检只执行 Linux 基础指标，隐藏未选择的中间件 profile 指标，并从已落盘 host-result-v1 JSON 以中文字段名打印已采集指标值。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/modules/registry.py",
    "inspect/ansible_runner.py",
    "inspect/render_stdout.py",
    "README.md",
    "tests/test_modules.py",
    "tests/test_ansible_runner.py",
    "tests/test_render_stdout.py",
    "tests/test_linux_basic.py",
    "contracts/contract-T-115-v1.md"
  ],
  "parent_task_id": "T-114",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "新增中间件 profile 配置",
      "修改 host-result-v1 schema",
      "新增 CLI 选项",
      "改变本地/远程执行路径",
      "系统 Python/Ansible fallback",
      "凭据和远程目标变更"
    ],
    "include": [
      "为模块注册表增加显式模块选择能力",
      "默认执行 linux_basic，保留显式 linux_common 扩展能力",
      "报告从 host-result-v1 JSON 渲染已采集指标的中文名称和值",
      "补充报告、模块选择和端到端事实源测试及文档"
    ]
  },
  "success_definition": "无中间件选择时事实源只包含六个 Linux 基础指标，报告不出现 unsupported_profile UNKNOWN，并按 JSON 中的 name、normalized_value/raw_value、unit 输出中文指标和值；未来可通过显式模块选择保留中间件扩展点。",
  "task_id": "T-115",
  "timeout_minutes": 30,
  "triggers": [],
  "verification_required": true
}

```
