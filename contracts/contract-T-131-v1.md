```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_ansible_runner.py tests/test_nginx.py tests/test_keepalived.py tests/test_cli.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "node C:/Users/SYH/.assembly-development/scripts/self-test.mjs"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "bash inspect.sh -H kylin01,kylin02,kylin03 --parallel 3"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:git"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-131-v1",
  "contract_sha256": "sha256:b8df808d6d150ac868764d8706867782ed3531d89ac672405603266f8153cdd7",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/ansible_runner.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/metrics.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/probe.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/cli.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_ansible_runner.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_nginx.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_keepalived.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_cli.py",
      "required": true
    },
    {
      "kind": "documentation",
      "path": "README.md",
      "required": true
    }
  ],
  "depends_on": [
    "T-130"
  ],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff",
    "vm-smoke"
  ],
  "forbidden_ops": [
    "force_push",
    "reset_hard",
    "clean",
    "secret_access"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "runtime/",
    "inventory/hosts.local.ini",
    "inspect.conf"
  ],
  "idempotency_key": "T-131-process-detection-and-parallelism",
  "input_artifacts": [
    {
      "path": "inspect/ansible_runner.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/metrics.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/probe.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/cli.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_ansible_runner.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_nginx.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_keepalived.py",
      "sha256": "",
      "version": "workspace"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "serial 参数只允许 1-3，默认保持 1；每台主机仍保留 probe 闸门和模块 bundle",
    "进程匹配使用 ps 的 PID/comm/args 结构锚点，避免匹配 inspect/Ansible 自身命令文本",
    "连接失败继续保持 ERROR/无业务结论，不能伪造 CRIT 指标"
  ],
  "network_scope": [
    "用户授权的 192.168.0.101 测试 VM"
  ],
  "non_goals": [
    "不把 CONNECTION_FAILED 改写成业务 CRIT；技术不可达仍显示 ERROR/无业务结论，避免伪造未采集的指标结果",
    "不默认扩大远程并发；默认 serial:1，用户通过 --parallel 3 明确启用最多三台并行"
  ],
  "objective": "修复 Nginx/Keepalived 进程发现被 Ansible raw 命令回显误判的问题，并为远程巡检增加最多 3 台主机并行的显式参数，同时保持不可达主机不执行指标采集和技术失败语义。",
  "output_schema": "task-report",
  "owned_paths": [
    "contracts/contract-T-131-v1.md",
    "inspect/ansible_runner.py",
    "inspect/metrics.py",
    "inspect/probe.py",
    "inspect/cli.py",
    "tests/test_ansible_runner.py",
    "tests/test_nginx.py",
    "tests/test_keepalived.py",
    "tests/test_cli.py",
    "docs/specs/ansible-execution.md",
    "docs/specs/nginx-middleware.md",
    "docs/specs/keepalived-middleware.md",
    "README.md"
  ],
  "parent_task_id": "T-130",
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260821-process-parallel",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "改变 host-result-v1 的技术 ERROR 与业务 CRIT 分离语义",
      "改变不可达主机的事实源结构或为不可达主机伪造业务指标",
      "修改 inventory 中的真实账号密码或测试机 inspect.conf",
      "修改报表布局、Elasticsearch 指标解析和本地执行路径"
    ],
    "include": [
      "Nginx/Keepalived/Elasticsearch 真实进程发现命令及动态发现前缀",
      "远程 Ansible serial 并行参数（CLI --parallel，范围 1-3）",
      "进程发现、playbook 生成和远程失败闸门回归测试",
      "README、Ansible 执行规格和中间件指标命令说明"
    ]
  },
  "success_definition": "Nginx/Keepalived 进程探测只认可 ps 进程名字段中的真实进程；不可达主机只执行一次 probe、无业务指标任务；远程可通过 --parallel 1..3 控制并发且默认行为不变；相关单元测试、自检、编译检查通过。",
  "task_id": "T-131",
  "timeout_minutes": 60,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-131 进程发现与远程并行

## 实现约束

- 进程存在性必须从 `ps` 的结构化列中确认真实进程名；命令文本中出现 `nginx`、`keepalived` 或 `elasticsearch` 不得计为运行。
- 动态配置/日志发现与进程存在性使用同一套真实进程筛选，不能回退到容易被命令回显污染的 `pgrep -fa`。
- `--parallel N` 只对远程 Ansible 生效，N 只能是 1、2、3；默认 N=1，明确传 `--parallel 3` 才同时最多巡检三台。
- 不可达主机在 probe 失败后跳过所有 metric bundle；保持技术 `ERROR`/无业务结论，不产生伪造的业务 `CRIT`。

## 停止规则

发现需要修改 host-result-v1 结构、改变技术失败与业务状态分离、放宽并发上限或覆盖测试机私有配置时停止并报告。
