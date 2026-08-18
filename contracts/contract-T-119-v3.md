```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_linux_basic.py tests/test_normalize.py tests/test_render_stdout.py"
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
      "test_command": "bash inspect.sh --local"
    }
  ],
  "contract_id": "contract-T-119-v3",
  "contract_sha256": "sha256:0bf4bfa6c68dc4f5c15f479b8bd83e7e7732d6b0d0b62a211de89ade6b762e2a",
  "contract_version": 1,
  "deliverables": [
    {
      "kind": "filesystem-collection",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "filesystem-normalization",
      "path": "inspect/normalize.py",
      "required": true
    },
    {
      "kind": "stdout-rendering",
      "path": "inspect/render_stdout.py",
      "required": true
    },
    {
      "kind": "regression-tests",
      "path": "tests/test_normalize.py",
      "required": true
    },
    {
      "kind": "regression-tests",
      "path": "tests/test_render_stdout.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/local-metrics-requirements.md",
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
  "network_scope": [],
  "non_goals": [
    "不新增文件系统指标 ID",
    "不改变磁盘阈值判定：主机级状态仍按所有挂载点最大使用率计算",
    "不采集或展示真实凭据"
  ],
  "objective": "将 Linux 基础磁盘指标从仅展示一个聚合值改为采集所有文件系统挂载点，并在 host-result-v1 JSON 中保存结构化挂载点与使用率，终端报告按‘挂载点 + 使用率’逐行输出。",
  "owned_paths": [
    "inspect/ansible_runner.py",
    "inspect/normalize.py",
    "inspect/schema/host-result-v1.schema.json",
    "inspect/render_stdout.py",
    "tests/test_normalize.py",
    "tests/test_render_stdout.py",
    "README.md",
    "docs/specs/local-metrics-requirements.md",
    "contracts/contract-T-119-v1.md",
    "docs/specs/host-result-v1.md"
  ],
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-004",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "中间件模块",
      "真实 inventory 和凭据",
      "受保护路径"
    ],
    "include": [
      "df -hT/df -i 全挂载点采集",
      "host-result-v1 evidence 中的结构化挂载点数据",
      "stdout 中文报表逐挂载点展示",
      "最大使用率继续用于既有阈值判定"
    ]
  },
  "success_definition": "local 与远程共用的磁盘采集命令不再限定根目录；每个磁盘指标 JSON 包含全部挂载点、使用率和挂载点字段；stdout 报表逐行显示挂载点与使用率；主机级 WARN/CRIT 仍按最大使用率判定；相关测试、自检和本地运行通过。",
  "task_id": "T-119",
  "timeout_minutes": 30,
  "verification_required": true
}

```

# T-119 全挂载点磁盘使用率（完整文档版）

将 `df -hT` 与 `df -i` 从根文件系统限定采集改为全文件系统采集。保留指标对象的聚合 `normalized_value` 作为最大使用率，用于兼容现有阈值判定；在 evidence 中增加结构化的挂载点明细，并同步更新正式 `host-result-v1` schema 与字段契约；终端报告读取 JSON 明细，以“挂载点 + 使用率”逐行输出。
