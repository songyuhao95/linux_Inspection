```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_ansible_runner.py tests/test_ansible_callback.py tests/test_inventory.py tests/test_g0_remote_runner.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect tests"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "bash inspect.sh -H inspection"
    }
  ],
  "contract_id": "contract-T-118-v1",
  "contract_sha256": "sha256:35914ac787114aec059dacba16544b3f5e0f0279df041e5553e241a809a57386",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "remote-ssh-policy-fix",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "regression-tests",
      "path": "tests/test_ansible_runner.py",
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
    },
    {
      "kind": "documentation",
      "path": "docs/g0-real-vm.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/ansible-execution.md",
      "required": true
    }
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
  "manual_gate_required": false,
  "network_scope": [
    "approved test VM SSH only"
  ],
  "non_goals": [
    "关闭 OpenSSH 对已知主机密钥变化的拒绝行为",
    "将密码写入命令行、环境快照或事实源"
  ],
  "objective": "修复远程密码 inventory 首次 SSH 连接因 host-key 前置检查失败的问题，并将该控制面失败正确分类为 CONNECTION_FAILED。",
  "owned_paths": [
    "inspect/ansible_runner.py",
    "tests/test_ansible_runner.py",
    "README.md",
    "docs/runbook.md",
    "docs/g0-real-vm.md",
    "docs/specs/ansible-execution.md",
    "contracts/contract-T-118-v1.md"
  ],
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-003",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "指标命令和 host-result-v1 JSON schema",
      "真实凭据、真实 inventory 和受保护路径",
      "run/events.ndjson、.claude/、run/reports/、linux-docx/",
      "force push、reset --hard、clean -fd"
    ],
    "include": [
      "inspect/ansible_runner.py 的 bundled Ansible SSH 环境变量和 callback 失败分类",
      "远程执行测试覆盖",
      "README.md、docs/runbook.md、docs/g0-real-vm.md、docs/specs/ansible-execution.md 文档说明"
    ]
  },
  "success_definition": "远程 runner 使用受控的 accept-new host-key 策略完成首次连接；host-key/sshpass 前置失败不再伪装为 PROBE_FAILED；相关单元测试、自检和真实测试虚拟机的双主机巡检通过；不泄露凭据。",
  "task_id": "T-118",
  "timeout_minutes": 30,
  "verification_required": true
}

```

# T-118 远程 SSH host-key 前置检查修复

远程 inventory 由 Ansible 原生读取认证变量。runner 使用 `ANSIBLE_HOST_KEY_CHECKING=False` 配合 OpenSSH `StrictHostKeyChecking=accept-new`，使密码 inventory 可在首次连接时工作，同时保留已知主机密钥变化的拒绝行为。连接前置失败统一归类为 `CONNECTION_FAILED`，不伪装成 probe 业务失败。
