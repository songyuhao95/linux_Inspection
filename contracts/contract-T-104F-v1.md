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
      "test_command": "python -c \"import sys,re; sys.path.insert(0,'.'); from inspect import normalize as n; doc=n.normalize_host_result({'schema_version':1,'host':{'name':'192.168.1.1','ip':'192.168.1.1'},'execution_status':'SUCCESS','metrics':[]}, run_id='r'); assert re.fullmatch(r'insp-[0-9]{14}-[A-Za-z0-9_.-]+', doc.get('inspection_id','')), doc.get('inspection_id'); print('AC-2 signature ok')\""
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
  "contract_id": "contract-T-104F-v1",
  "contract_sha256": "sha256:64e6ebfc78c288dded66f105be9f3a3077de218c5bf19c2bc8eed0db11e5f97b",
  "contract_version": 2,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/normalize.py",
      "required": true
    },
    {
      "kind": "test",
      "path": "tests/test_normalize.py",
      "required": true
    },
    {
      "kind": "task-report",
      "path": "run/reports/T-104.md",
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
    "inspect/ansible_runner.py",
    "inspect/probe.py",
    "inspect/fact_source.py",
    "inspect/schema/",
    "inspect/data/",
    "inspect/templates/",
    "inspect/render_stdout.py",
    "inspect/render_xlsx.py",
    "inspect/render_html.py",
    "tests/test_cli.py",
    "tests/test_metrics.py",
    "tests/test_config.py",
    "tests/test_inventory.py",
    "tests/test_ansible_runner.py",
    "tests/test_fact_source.py",
    "tests/test_render_stdout.py",
    "tests/test_render_xlsx.py",
    "tests/test_render_html.py",
    "tests/test_e2e.py",
    "tests/fixtures/",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt"
  ],
  "idempotency_key": "run-20260814-001:T-104F:v1",
  "input_artifacts": [
    {
      "path": "docs/specs/host-result-v1.md",
      "sha256": "fb101b1c0bc21371bc08e27f7a7c32a3d130cbf0efc9a1c2c2ca1aa9ad44ba1f",
      "version": "G1-approved"
    },
    {
      "path": "inspect/normalize.py",
      "sha256": "verify-medium",
      "version": "T-104-integrated"
    },
    {
      "path": "run/reports/T-104.md",
      "sha256": "verify-medium",
      "version": "T-104-delivered"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "修复只触及 inspection_id 派生与脱敏顺序",
    "新增用例覆盖 IP 键/含关键字 host 键",
    "脱敏幂等性保持（既有测试不动）",
    "无凭据、不连接主机、不执行 DOCX 命令"
  ],
  "network_scope": [],
  "non_goals": [
    "Low 项修复（后续版本）",
    "其他任务范围功能"
  ],
  "objective": "修复 T-104 独立验证发现的 Medium 缺陷：normalize 对派生标识符过度脱敏，导致 host 键为 IP/含凭据关键字时 inspection_id 含 <IP>/<REDACTED> 不匹配 schema pattern，事实源落盘被拒（exit 10），破坏 normalize 输出必可落盘不变量。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/normalize.py",
    "tests/test_normalize.py",
    "run/reports/T-104.md"
  ],
  "parent_task_id": "T-104",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260814-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "任何其他功能修改（脱敏机制本身、原子写、判定顺序等已验证 PASS 部分不动）",
      "Low 项修复（内嵌校验器宽松、C8 单测缺失）——记录为已知限制即可",
      "修改已交付 T-101..T-103 文件、已批准文档、linux-docx/、contracts/、run/events.ndjson",
      "访问任何目标主机、网络服务或秘密"
    ],
    "include": [
      "inspect/normalize.py：派生标识符（inspection_id）生成与脱敏顺序修复——标识符先基于原始 host 键生成合法 ID（host 键脱敏为安全字符集内占位，如 <IP>→ip、<REDACTED>→redacted），再对业务字段脱敏；确保输出必过自身 schema 校验",
      "tests/test_normalize.py：新增用例（IP 键 host、含 secret 关键字 host 键→inspection_id 合法且可落盘、业务字段脱敏不受影响）",
      "run/reports/T-104.md：补记 T-104F 修复记录"
    ]
  },
  "success_definition": "修复后：host 键为 IP（如 192.168.1.1）或含凭据关键字（如 node-secret-01）时，normalize 输出 inspection_id 符合 schema pattern（^insp-[0-9]{14}-[A-Za-z0-9_.-]+$）且可落盘；脱敏仍对业务字段（evidence/error 消息/日志）生效且幂等；host 名本身按脱敏规则处理（输出中不出现明文 IP/凭据）；全量测试通过；受保护路径零改动。",
  "task_id": "T-104F",
  "timeout_minutes": 60,
  "triggers": [
    "修复导致脱敏失效（明文 IP/凭据出现）",
    "修复导致已验证 PASS 行为回归",
    "需要修改 owned_paths 之外文件"
  ],
  "verification_required": true,
  "worktree": null
}

```

# T-104F 标识符过度脱敏修复合同 v1

## 背景（T-104 独立验证 Medium 发现，主会话转述）

`normalize_host_result` 的 `_sweep_strings` 全文档递归兜底把派生标识符一并脱敏：host 键为 IP（Ansible inventory 按 IP 作 host 键是常见用法）或含凭据关键字时，`inspection_id` 变成 `insp-<时间戳>-<IP>` 或含 `<REDACTED>`，违反 schema `inspection_id` pattern，`validate_host_result` 拒绝、`fact_source` 落盘失败（exit 10），破坏"normalize 输出必可落盘"不变量。fail-safe 方向（不泄露）正确，但需修复标识符生成逻辑。

## 必需步骤

1. 修复 `inspect/normalize.py`：inspection_id 派生改为先对 host 键做安全字符集映射（IP/特殊字符→占位，如 ip/redacted/host 哈希后缀），生成合法 ID，再对业务字段（evidence/error 消息/日志）脱敏；确保输出必过自身 schema 校验（inspection_id pattern、host 字段按脱敏规则不出现明文）。
2. `tests/test_normalize.py` 新增用例：IP 键 host（如 192.168.1.1）→ inspection_id 合法且落盘成功；含 secret 关键字 host 键（如 node-secret-01）→ 同理；业务字段脱敏不受影响（既有对抗用例保持全绿）。
3. `run/reports/T-104.md` 补记 T-104F 修复记录（含 AC 证据）。
4. 运行 AC-1..AC-2，逐条记录输入/预期/实际退出码/证据/结论；报告含受保护路径 git diff 验证。
5. 不 commit、不 push；交付 worktree 路径与文件清单，由主会话集成。

## 停止规则

修复导致脱敏失效（明文 IP/凭据出现）、已验证 PASS 行为回归、需要修改 owned_paths 之外文件 → 立即停止报告。
