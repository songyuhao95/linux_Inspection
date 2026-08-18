```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_inventory.py tests/test_ansible_runner.py tests/test_g0_remote_runner.py tests/test_cli.py"
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
  "contract_id": "contract-T-116-v1",
  "contract_sha256": "sha256:d27c61de7de03905f316f383d4bd339c54cf9ad25ba90fa3a2831def16b4a255",
  "contract_version": 3,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "default-inventory-selection",
      "path": "inspect/inventory.py",
      "required": true
    },
    {
      "kind": "inventory-template",
      "path": "inventory/hosts.ini.example",
      "required": true
    },
    {
      "kind": "credential-source-compatible-runner",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_inventory.py",
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
    "diff"
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
    "linux-docx/",
    "inventory/hosts.ini"
  ],
  "idempotency_key": "T-116",
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "默认 inventory 模板不包含真实凭据；实际 inventory/hosts.ini 只在本地使用并被 gitignore 忽略。",
    "inventory 解析器继续不把认证变量读入 HostEntry、JSON、事件或报表；凭据只由 Ansible 读取。"
  ],
  "network_scope": [],
  "objective": "支持项目内本地 inventory 配置主机组、SSH 用户和密码；-H 使用主机组或 IP 时复用 inventory 并由项目内 Ansible 执行，避免每次设置认证环境变量。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/inventory.py",
    "inspect/ansible_runner.py",
    "inspect/cli.py",
    "inventory/hosts.ini.example",
    "README.md",
    ".gitignore",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_g0_remote_runner.py"
  ],
  "parent_task_id": "T-115",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "真实凭据提交到 Git",
      "修改指标采集逻辑",
      "新增远程目标",
      "系统 Python/Ansible fallback",
      "密码进入 argv/JSON/事件/报表"
    ],
    "include": [
      "默认 inventory/hosts.ini 解析",
      "-H group/ip 复用默认 inventory",
      "允许 Ansible 从 inventory 读取认证变量",
      "保留 -i 和环境变量兼容路径",
      "模板、文档和测试"
    ]
  },
  "success_definition": "在存在 inventory/hosts.ini 时，bash inspect.sh -H <group-or-ip-list> 直接使用该 inventory 及其 Ansible 认证变量；不再要求 INSPECT_REMOTE_USER/INSPECT_ASK_PASS；解析结果与事实源不泄漏认证变量；无默认 inventory 时保留原有临时 inventory 与显式环境变量路径。",
  "task_id": "T-116",
  "timeout_minutes": 30,
  "triggers": [],
  "verification_required": true
}

```