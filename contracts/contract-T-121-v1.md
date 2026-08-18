```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q --basetemp=.test-tmp tests/test_normalize.py tests/test_render_stdout.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m pytest -q --basetemp=.test-tmp tests/test_metrics.py tests/test_linux_basic.py"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect tests"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-5",
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
  "contract_id": "contract-T-121-v1",
  "contract_sha256": "sha256:2ce163c77998b3f5f108479f42bdaae3ae6806aa3864ea623f71341db41cd606",
  "contract_version": 2,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/normalize.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/render_stdout.py",
      "required": true
    },
    {
      "kind": "contract",
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
      "path": "tests/test_render_stdout.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/local-metrics-requirements.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "docs/specs/host-result-v1.md",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    }
  ],
  "depends_on": [],
  "evidence_types": [
    "test-result",
    "schema-validation",
    "diff",
    "local-vm-run",
    "remote-vm-run"
  ],
  "forbidden_ops": [
    "deploy",
    "force_push",
    "secret_access",
    "git_reset_hard",
    "git_clean"
  ],
  "forbidden_paths": [
    "inspect/ansible_runner.py",
    "run/events.ndjson",
    ".claude/",
    "run/reports/",
    "linux-docx/",
    "inventory/"
  ],
  "idempotency_key": "T-121",
  "manual_gate_required": false,
  "max_attempts": 2,
  "network_scope": [],
  "non_goals": [
    "不新增负载阈值等级；load > 核数仍按文档未定义边界处理",
    "不将负载值误解释为 CPU 使用率百分比"
  ],
  "objective": "扩展 Linux 系统负载事实与终端展示：保留 local.cpu.load_1m 指标 ID，JSON 结构化保存 1/5/15 分钟负载及 CPU 核数，stdout 按三行输出准确中文描述，并将单位描述改为‘1分钟系统负载：值，负载 <= CPU 核数：正常’语义。",
  "owned_paths": [
    "inspect/metrics.py",
    "inspect/normalize.py",
    "inspect/render_stdout.py",
    "inspect/schema/host-result-v1.schema.json",
    "tests/test_normalize.py",
    "tests/test_render_stdout.py",
    "docs/specs/local-metrics-requirements.md",
    "docs/specs/host-result-v1.md",
    "README.md",
    "contracts/contract-T-121-v1.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "不新增 local.cpu.load_5m/local.cpu.load_15m 指标 ID，保持现有 10 个指标注册表兼容；仅更新 load_1m 的注册表单位描述",
      "不改变 Ansible 或本地采集命令",
      "不改变整体 metric status 仍基于 1 分钟负载的既有兼容语义，除非测试证明现有结构必须调整",
      "不伪造采集数据、不读取真实凭据"
    ],
    "include": [
      "复用现有 /proc/loadavg + nproc 采集结果",
      "在 host-result-v1 JSON evidence.details 中保存 window/load/cpu_cores/status/judgement",
      "stdout 从 JSON 事实源读取并输出 1分钟、5分钟、15分钟三行",
      "每个时间窗口按 load <= CPU 核数输出正常判定；load > CPU 核数沿用未定义等级 UNKNOWN",
      "schema、单元测试、正式规格与 README 同步"
    ]
  },
  "success_definition": "现有 fixture 和真实路径均能生成包含 1m/5m/15m 负载明细的合法 JSON；stdout 输出三行准确中文描述且不再显示‘相对核数，无量纲’；旧事实源无 details 时仍不崩溃；相关测试、自检、schema 校验和 git diff --check 通过。",
  "task_id": "T-121",
  "timeout_minutes": 30,
  "verification_required": true
}

```

# T-121 系统负载三窗口展示

复用现有 `/proc/loadavg` 输出中的 1 分钟、5 分钟、15 分钟负载。事实源在单个 `local.cpu.load_1m` 指标的 `evidence.details` 中保存三个窗口的结构化明细，终端报表从 JSON 读取并逐行展示。每行使用“负载 <= CPU 核数：正常”的中文判定语义；超过核数时不得发明 WARN/CRIT，继续显示 UNKNOWN/未定义等级。

停止规则：发现必须新增指标 ID、改变整体状态语义、或需要修改禁止路径时停止并上报。
