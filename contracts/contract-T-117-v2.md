```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "Test(-not (Test-Path relay.md)); git ls-files --error-unmatch inventory/hosts.ini"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_inventory.py tests/test_g0_remote_runner.py"
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
  "contract_id": "contract-T-117-v2",
  "contract_sha256": "sha256:0dbca223a35089d568645d7ebe94672a632675cc32ebdb56c5e218b7f84c0fb9",
  "contract_version": 2,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "sanitized-inventory-template",
      "path": "inventory/hosts.ini",
      "required": true
    },
    {
      "kind": "inventory-selection",
      "path": "inspect/inventory.py",
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
    },
    {
      "kind": "documentation",
      "path": "docs/runbook.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff"
  ],
  "forbidden_ops": [
    "secret_logging",
    "network_installation",
    "force_push",
    "reset_hard",
    "clean_fd"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/"
  ],
  "idempotency_key": "T-117-v2",
  "input_artifacts": [
    {
      "path": "README.md",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "docs/runbook.md",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "inspect/inventory.py",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "inventory/hosts.ini.example",
      "sha256": "",
      "version": "HEAD"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "inventory/hosts.ini 只提交注释示例；真实凭据不进入 Git",
    "优先使用 inventory/hosts.local.ini，默认 -H 不要求环境变量",
    "纯注释模板不得阻断既有临时 inventory 回退路径"
  ],
  "network_scope": [],
  "non_goals": [
    "不执行真实远程巡检"
  ],
  "objective": "删除 relay.md，改用项目文档作为开发事实源，并将公开的 inventory/hosts.ini 注释模板与本地私有 inventory 自动选择纳入远程执行路径。",
  "output_schema": "task-report",
  "owned_paths": [
    "relay.md",
    "inventory/hosts.ini",
    "inventory/hosts.local.ini",
    ".gitignore",
    "inspect/inventory.py",
    "README.md",
    "docs/runbook.md",
    "docs/g0-real-vm.md",
    "docs/local-vm-deploy.md",
    "runtime/README.md",
    "docs/specs/ansible-execution.md",
    "tests/test_inventory.py"
  ],
  "parent_task_id": "T-116",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-002",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "真实凭据和真实内网地址",
      "修改指标采集和 JSON schema",
      "修改 run/events.ndjson、.claude/、run/reports/、linux-docx/",
      "force push、reset --hard、clean -fd"
    ],
    "include": [
      "删除 relay.md",
      "创建并跟踪 inventory/hosts.ini 脱敏注释模板",
      "忽略 inventory/hosts.local.ini 等本地私有 inventory 变体",
      "默认 -H 自动优先使用有效的 inventory/hosts.local.ini，其次使用有主机的 inventory/hosts.ini；纯注释模板视为未配置并回退兼容路径",
      "更新 inventory 选择测试和 Ansible 认证路径测试",
      "更新 README.md、docs/runbook.md、docs/g0-real-vm.md、docs/local-vm-deploy.md、runtime/README.md、docs/specs/ansible-execution.md 的文档入口或 inventory 说明"
    ]
  },
  "success_definition": "relay.md 不再存在于工作树和提交中；inventory/hosts.ini 被 Git 跟踪且只有注释形式的脱敏示例；inventory/hosts.local.ini 被忽略并在存在有效主机时由默认 -H 自动优先使用；无有效本地 inventory 时回退旧临时路径；README、docs 和 runtime 文档说明新的来源与配置流程；测试、自检和 Git 检查通过。",
  "task_id": "T-117",
  "timeout_minutes": 30,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-117 v2 文档入口、公开 inventory 模板与私有 inventory 自动选择

按用户要求删除 relay.md。仓库公开 `inventory/hosts.ini` 仅作为注释格式模板，真实配置使用被忽略的 `inventory/hosts.local.ini`；默认远程 `-H` 自动选择有效配置，保持无配置时的兼容回退。

发现纯注释模板会与原有解析逻辑冲突时，必须修改 inventory 选择和测试，不得让默认远程巡检因模板存在而报“无任何主机”。

停止规则：需要真实凭据、真实内网地址、修改受保护路径或改变指标/JSON 契约时停止并报告。
