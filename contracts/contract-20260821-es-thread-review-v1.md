```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest tests/test_elasticsearch.py tests/test_ansible_runner.py -q"
    }
  ],
  "allowed_tools": [
    "Read",
    "Bash: pytest/rg only"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-20260821-es-thread-review-v1",
  "contract_sha256": "sha256:e90916ec860540dacf5b06787dcb5a23e920526d7fd5fe2e8769331a11b22577",
  "contract_version": 2,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "review-report",
      "path": "run/reports/T-20260821-VERIFY-ES-THREAD.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "review-findings",
    "test-result"
  ],
  "forbidden_ops": [
    "secret_access",
    "network_access",
    "write_source",
    "deploy",
    "force_push"
  ],
  "forbidden_paths": [
    "inspect/",
    "tests/",
    "docs/",
    "README.md"
  ],
  "idempotency_key": "T-20260821-VERIFY-ES-THREAD",
  "input_artifacts": [],
  "manual_gate_required": false,
  "max_attempts": 1,
  "mitigations": [],
  "network_scope": [],
  "non_goals": [
    "不实现新功能",
    "不提交代码",
    "不执行 Git push",
    "不连接虚拟机"
  ],
  "objective": "只读复核 Elasticsearch 解析修复和远程逐主机线程并发改造，识别会导致 UNKNOWN、误判或并发回归的问题。",
  "output_schema": "task-report",
  "owned_paths": [
    "run/reports/T-20260821-VERIFY-ES-THREAD.md"
  ],
  "parent_task_id": null,
  "phase": "verify",
  "risk_level": "medium",
  "run_id": "run-20260821-es-thread-refactor-001",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "runtime/",
      "inventory/",
      "inspect.conf",
      "out/",
      "run/"
    ],
    "include": [
      "inspect/ansible_runner.py",
      "inspect/normalize.py",
      "inspect/cli.py",
      "tests/",
      "docs/"
    ]
  },
  "success_definition": "输出带文件和行号的审查结论；不修改实现文件、不访问真实凭据、不执行远程主机操作。",
  "task_id": "T-20260821-VERIFY-ES-THREAD",
  "timeout_minutes": 20,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# 复核任务

只读检查当前工作树中的 Elasticsearch 发现/解析逻辑、远程逐主机线程执行逻辑及其测试。重点确认：

1. Elasticsearch server JVM 与 launcher JVM 的路径发现、配置中的 `path.logs` 优先级、监听地址/端口和 HTTP 状态解析不会把 curl 错误误判为业务值。
2. `inspect.sh` 远程执行是否严格做到一主机一个 Ansible playbook、控制端线程并发且最大 10；不可达主机不会发起后续指标采集。
3. 测试是否覆盖新契约，是否存在旧的 1~3 并发假设。

发现问题时仅写入指定报告，按 P0/P1/P2 分级并给出文件、行号和建议；不要修改源文件。
