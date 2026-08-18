```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_cli.py -k 'report or xlsx or html'"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "git diff --check"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-124-v1",
  "contract_sha256": "sha256:b6d2b95c554c08e1a90e0a89a948c75daec463f92980d59a2820b7989ca97473",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_cli.py",
      "required": true
    },
    {
      "kind": "dependency-declaration",
      "path": "requirements.txt",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/cli-contract.md",
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
    "deploy",
    "force_push",
    "secret_access",
    "git_reset_hard",
    "git_clean"
  ],
  "forbidden_paths": [
    "run/",
    ".claude/",
    ".test-tmp/",
    "out/",
    "runtime/ansible/",
    "runtime/lib/"
  ],
  "idempotency_key": "T-124",
  "input_artifacts": [
    {
      "path": "inspect/cli.py",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "requirements.txt",
      "sha256": "",
      "version": "working-tree"
    },
    {
      "path": "docs/specs/cli-contract.md",
      "sha256": "",
      "version": "working-tree"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "preserve renderer APIs",
    "test both omitted and explicit output paths",
    "do not stage runtime artifacts"
  ],
  "network_scope": [],
  "non_goals": [
    "不在本合同内重新打包完整跨平台 Python runtime",
    "不修改 Ansible 执行逻辑",
    "不提交真实凭据"
  ],
  "objective": "将 Excel/HTML 报表 CLI 简化为 --excel [PATH] 与 --html [PATH]，补齐项目运行时 pandas/xlsxwriter 依赖声明，并更新测试与用户文档。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/cli.py",
    "tests/test_cli.py",
    "requirements.txt",
    "README.md",
    "docs/",
    "runtime/README.md",
    "contracts/contract-T-124-v1.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-report-options",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "run/",
      ".claude/",
      ".test-tmp/",
      "out/",
      "runtime/ansible/",
      "runtime/lib/"
    ],
    "include": [
      "inspect/cli.py",
      "tests/test_cli.py",
      "requirements.txt",
      "README.md",
      "docs/",
      "runtime/README.md",
      "contracts/contract-T-124-v1.md"
    ]
  },
  "success_definition": "不再要求 --xlsx-out/--html-out；--excel/--html 可选接收输出路径，缺省写入当前工作目录；依赖声明含 pandas 与 xlsxwriter；相关测试和文档通过校验。",
  "task_id": "T-124",
  "timeout_minutes": 30,
  "triggers": [
    "report CLI contract change",
    "runtime dependency change"
  ],
  "verification_required": true,
  "worktree": null
}

```

# 任务说明

实现报表命令行语法简化，并补齐项目内报表依赖声明。`--excel` 和 `--html` 需要分别支持可选路径；未提供路径时输出到当前脚本工作目录。旧的 `--xlsx-out` 和 `--html-out` 不再作为 CLI 选项。同步更新 CLI 规格、运行手册、README 和测试。

## 停止规则

如果现有文档或代码与上述目标冲突，停止并报告，不要静默兼容或扩大范围；禁止修改运行状态目录和已打包 runtime 文件。
