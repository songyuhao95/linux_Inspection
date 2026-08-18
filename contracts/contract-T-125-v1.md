```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "bash inspect.sh --local --html --excel"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "ssh aqwh@192.168.0.101 'cd /data/inspect/linux_Inspection && bash inspect.sh --local --html --excel'"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "git push origin main"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:scp",
    "Bash:ssh",
    "Bash:git",
    "Bash:test"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-125-v1",
  "contract_sha256": "sha256:16748cf7c360c7c11a8d5f92a4f67dc88e6379900c48adf764654c53343b343f",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "linux-runtime-dependencies",
      "path": "runtime/lib/python3.12/site-packages",
      "required": true
    },
    {
      "kind": "dependency-lock",
      "path": "runtime/report-requirements.lock",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "runtime/README.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "git-diff",
    "vm-e2e",
    "push-result"
  ],
  "forbidden_ops": [
    "force_push",
    "reset_hard",
    "clean",
    "delete_git",
    "commit_secrets"
  ],
  "forbidden_paths": [
    "run/**",
    ".claude/**",
    ".test-tmp/**",
    "runtime/ansible/**",
    "runtime/bin/**",
    "inventory/hosts.local.ini"
  ],
  "idempotency_key": "T-125-linux-runtime-report-deps",
  "input_artifacts": [
    {
      "path": "runtime/manifest.json",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "runtime/README.md",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "requirements.txt",
      "sha256": "",
      "version": "HEAD"
    }
  ],
  "manual_gate_required": true,
  "max_attempts": 2,
  "mitigations": [
    "pin exact versions",
    "verify import and end-to-end output on Kylin Linux",
    "keep Windows runtime separate",
    "do not fallback to system Python"
  ],
  "network_scope": [
    "192.168.0.101:22",
    "origin git remote"
  ],
  "non_goals": [
    "不把 Windows 二进制依赖混入 Linux runtime",
    "不在 inspection 执行时联网安装依赖",
    "不修改运行产物 out/ 和 run/"
  ],
  "objective": "将 Linux x86_64/Python 3.12 报表依赖 pandas、xlsxwriter 及其运行时依赖作为项目内 runtime 内容提交，使新环境无需再次安装即可生成 Excel/HTML 报表。",
  "output_schema": "task-report",
  "owned_paths": [
    "runtime/lib/python3.12/site-packages/**",
    "runtime/report-requirements.lock",
    "runtime/README.md",
    "docs/g0-real-vm.md",
    "docs/local-vm-deploy.md",
    "docs/runbook.md",
    "README.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-linux-runtime",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "改变指标采集逻辑",
      "替换 bundled Ansible",
      "提交真实 inventory 凭据",
      "修改 run/ 运行时状态"
    ],
    "include": [
      "同步测试虚拟机中已验证的 Linux CPython 3.12 site-packages",
      "更新 runtime 依赖锁定与运行说明",
      "更新部署/真实虚拟机文档",
      "验证本地和虚拟机报告生成",
      "提交并推送 origin/main"
    ]
  },
  "success_definition": "runtime/lib/python3.12/site-packages 内包含经 Kylin Linux 目标验证的依赖；存在可审查的精确版本锁定说明；文档说明 Linux 目标与 Windows runtime 的边界；本地与 192.168.0.101 端到端报告验证通过；变更提交并推送 origin/main。",
  "task_id": "T-125",
  "timeout_minutes": 60,
  "triggers": [
    "platform-specific native wheels"
  ],
  "verification_required": true,
  "worktree": null
}

```
---
本次任务只处理 Linux 目标 runtime 报表依赖。依赖包来自已验证的测试虚拟机，不在检查执行时联网安装。安装内容必须直接进入项目 runtime/lib/python3.12/site-packages，确保全新 Linux checkout 可直接运行 --html/--excel。
