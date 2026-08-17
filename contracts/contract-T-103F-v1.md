```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python scripts-verify/verify-allowlist-h1.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python scripts-verify/verify-allowlist-h2.py"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_ansible_runner.py -q"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_inventory.py -q"
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "python -c \"from pathlib import Path; s=Path('run/reports/T-103.md').read_text(encoding='utf-8'); assert '34' in s and '62' in s\" "
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
  "contract_id": "contract-T-103F-v1",
  "contract_sha256": "sha256:deef0198a82104aebe2f760b5d94a54696fd4e5fc515ec44d76de0cc49671b8a",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_ansible_runner.py",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-103.md",
      "required": true
    },
    {
      "kind": "verification-script",
      "path": "scripts-verify/verify-allowlist-h1.py",
      "required": true
    },
    {
      "kind": "verification-script",
      "path": "scripts-verify/verify-allowlist-h2.py",
      "required": true
    }
  ],
  "depends_on": [],
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
    "inspect/probe.py",
    "inspect/data/",
    "inspect/schema/",
    "inspect/normalize.py",
    "inspect/fact_source.py",
    "inspect/render_stdout.py",
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "inspect/templates/",
    "tests/test_cli.py",
    "tests/test_metrics.py",
    "tests/test_config.py",
    "tests/test_inventory.py",
    "tests/fixtures/",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt"
  ],
  "idempotency_key": "run-20260814-001:T-103F:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/ansible-execution.md",
      "sha256": "3dc03751cec2ad3491903737553cdf5a7c49115d0101d6f368b917c68128e070",
      "version": "G1-approved"
    },
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "verify-failed",
      "version": "T-103-integrated"
    },
    {
      "path": "run/reports/T-103.md",
      "sha256": "verify-failed",
      "version": "T-103-delivered"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "修复只触及 _tokenize/validate_command_specs 与对应测试，不动已验证部分",
    "对抗用例全部固化进 tests/test_ansible_runner.py",
    "修正报告用例数与安全声明",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "接线 cli.py 到 ansible_runner（G0 事项）",
    "host_deadline_exceeded 调用点接线（G0 事项，记录为已知限制）",
    "其他任务范围功能"
  ],
  "objective": "修复 T-103 独立验证发现的 2 个 High 级 allow-list 缺陷：H-1（_tokenize 对裸 $/反引号死循环挂起）与 H-2（双引号内命令替换/反引号绕过 allow-list），并更正任务报告失实处。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/ansible_runner.py",
    "tests/test_ansible_runner.py",
    "run/reports/T-103.md",
    "scripts-verify/"
  ],
  "parent_task_id": "T-103",
  "phase": "implement",
  "risk_level": "high",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "任何其他功能修改（失败分类、fixture 模式、playbook 生成等已验证 PASS 部分不动）",
      "修改已交付 T-101/T-102 文件、已批准文档、linux-docx/、contracts/、run/events.ndjson",
      "访问任何目标主机、网络服务或秘密"
    ],
    "include": [
      "inspect/ansible_runner.py：_tokenize 与 validate_command_specs 修复（H-1 死循环、H-2 双引号/反引号/命令替换绕过）",
      "tests/test_ansible_runner.py：新增对抗用例（裸 $/反引号不挂起、双引号内 $()/反引号/$VAR 被拒绝、合法命令仍接受）",
      "run/reports/T-103.md：更正用例数（test_inventory 34 / test_ansible_runner 62 / 合计 96）与 allow-list 声明（不得再称注入类命令一律拒绝，除非修复后属实）"
    ]
  },
  "success_definition": "修复后：parse_binaries/validate_command_specs 对 H-1/H-2 全部复现用例拒绝或安全处理（不挂起、不绕过）；新增对应对抗测试固化；tests/test_inventory.py 与 tests/test_ansible_runner.py 全部通过；run/reports/T-103.md 更正用例数与 allow-list 声明；受保护路径零改动。",
  "task_id": "T-103F",
  "timeout_minutes": 60,
  "triggers": [
    "修复导致已验证 PASS 行为回归（playbook 生成/fixture 模式/失败分类）",
    "H-1/H-2 复现用例仍挂起或仍被接受",
    "需要修改 owned_paths 之外文件"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-103F allow-list 安全缺陷修复合同 v1

## 背景（独立验证结论，主会话转述）

T-103 独立验证总体 FAIL，2 个 High 级缺陷已实证：

- **H-1**：`inspect/ansible_runner.py:409-433` `_tokenize` 对裸 `$`/反引号死循环挂起（复现：`ar.parse_binaries('free -m; $(rm -rf /)')` 等 3 秒超时无返回；`validate_command_specs` 同型触发）。
- **H-2**：双引号内 `$()`/反引号被整体当参数跳过 → 绕过 allow-list（复现：`CommandSpec(..., 'free -m "$(rm -rf /)"', ...)` 被 ACCEPT）；shell 在双引号内会展开命令替换，G0 启用真实执行后即目标主机命令执行风险。
- 报告失实：用例数实为 test_inventory 34 / test_ansible_runner 62 / 合计 96（报告称 36/98）；§6"注入类命令一律拒绝"夸大。

## 必需步骤

1. 修复 `inspect/ansible_runner.py` `_tokenize` 与 `validate_command_specs`：H-1 不得死循环（裸 `$`/反引号安全拒绝）；H-2 双引号内命令替换/反引号/$VAR 一律拒绝；合法命令（指标注册表命令）仍接受。
2. 在 `tests/test_ansible_runner.py` 新增对抗用例固化：H-1 三例（不挂起、拒绝）、H-2 四例（拒绝）、合法命令对照（接受）。
3. 更正 `run/reports/T-103.md`：用例数 34/62/96；allow-list 声明与修复后实际行为一致；补记"G0 真实执行前需接线 host_deadline_exceeded"为已知限制。
4. 编写两个验证脚本 `scripts-verify/verify-allowlist-h1.py` 与 `scripts-verify/verify-allowlist-h2.py`（owned_paths 已含 scripts-verify/）：H1 脚本对 `free -m; $(rm -rf /)`、`free -m; \`whoami\``、`free -m $` 三个输入调用 `inspect.ansible_runner.parse_binaries`，每个调用必须在 2 秒内返回且不得接受为合法（拒绝或抛异常均可，挂起即失败，脚本整体超时上限 20 秒由外部执行兜底）；H2 脚本对 `free -m "$(rm -rf /)"`、`free -m "\`whoami\`"`、`cat /proc/loadavg "$(rm -rf /)"`、`df -hT "/tmp;$(rm -rf /)"` 四个输入调用 `parse_binaries`，每个必须在 2 秒内返回且必须被拒绝（不得返回可执行名或放行，接受即失败）。两个脚本均在主仓库根目录执行，退出码 0=通过。
5. 运行 AC-1..AC-5，逐条记录输入/预期/实际退出码/证据/结论；报告含受保护路径 git diff 验证。
6. 不 commit、不 push；交付 worktree 路径与文件清单，由主会话集成并重新独立验证。

## 停止规则

修复导致已验证 PASS 部分回归、H-1/H-2 复现用例仍挂起或被接受、需要修改 owned_paths 之外文件 → 立即停止报告。
