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
      "test_command": "python -m pytest tests/test_render_xlsx.py -q"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "ssh aqwh@192.168.0.101 'cd /data/inspect/linux_Inspection && bash inspect.sh --local --excel out/local-detail-smoke.xlsx'"
    },
    {
      "ac_id": "AC-5",
      "expected_exit": 0,
      "test_command": "git push origin main"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test",
    "Bash:python",
    "Bash:git"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-126-v1",
  "contract_sha256": "sha256:a9ebe02761d9cbf09bf657960b8bcdd1ac3bc40084997df279da4ef346df0261",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_xlsx.py",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_render_xlsx.py",
      "required": true
    },
    {
      "kind": "spec-update",
      "path": "docs/specs/reporting-roadmap.md",
      "required": true
    },
    {
      "kind": "runbook-update",
      "path": "docs/runbook.md",
      "required": false
    },
    {
      "kind": "status-update",
      "path": "README.md",
      "required": false
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
    "commit_secrets",
    "network_scan"
  ],
  "forbidden_paths": [
    "run/**",
    ".claude/**",
    ".test-tmp/**",
    "out/**",
    "inventory/hosts.local.ini",
    "runtime/**"
  ],
  "idempotency_key": "T-126-excel-local-detail-rows",
  "input_artifacts": [
    {
      "path": "inspect/render_xlsx.py",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "docs/specs/reporting-roadmap.md",
      "sha256": "",
      "version": "HEAD"
    },
    {
      "path": "docs/specs/host-result-v1.md",
      "sha256": "",
      "version": "HEAD"
    }
  ],
  "manual_gate_required": true,
  "max_attempts": 2,
  "mitigations": [
    "preserve JSON facts and stdout/HTML",
    "add fixture-based row-shape tests",
    "inspect generated workbook on authorized VM"
  ],
  "network_scope": [
    "origin git remote",
    "192.168.0.101:22 for authorized VM validation"
  ],
  "non_goals": [
    "不在渲染层二次采集或执行命令",
    "不将事实源中的 source_anchor/evidence_summary/provenance 删除",
    "不把多个挂载点聚合成单行"
  ],
  "objective": "改进 Excel Local 报表，使主机 IP、全部负载周期、全部文件系统挂载点、清晰阈值说明和指标复现命令在明细中可见。",
  "output_schema": "task-report",
  "owned_paths": [
    "inspect/render_xlsx.py",
    "tests/test_render_xlsx.py",
    "docs/specs/reporting-roadmap.md",
    "docs/runbook.md",
    "README.md",
    "contracts/contract-T-126-v1.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-excel-detail",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "改变 Linux 指标采集事实源 schema",
      "改变 stdout/HTML 报表行为",
      "修改中间件指标采集",
      "修改 runtime 依赖打包",
      "提交真实 inventory、凭据或运行产物"
    ],
    "include": [
      "inspect/render_xlsx.py 的 Local Sheet 行展开与列结构",
      "Excel 报表相关测试",
      "对应报告规格/运行文档的字段说明"
    ]
  },
  "success_definition": "Local Sheet 按事实源完整展开 1/5/15 分钟负载及每个挂载点的磁盘/inode 指标；host 后紧跟 ip；删除 source_anchor/evidence_summary/provenance 列，仅保留清晰 threshold_rule 并新增 command 列；本地测试和授权 Kylin VM Excel 生成验证通过。",
  "task_id": "T-126",
  "timeout_minutes": 45,
  "triggers": [
    "report schema presentation change",
    "multi-row metric expansion"
  ],
  "verification_required": true,
  "worktree": null
}

```
---
本合同只覆盖 Excel Local 明细展示。事实源 JSON 仍是唯一事实源；渲染层只读取已采集字段，不执行命令。对于负载、磁盘和 inode，报表必须逐条展开已有 JSON 中的周期/挂载点明细。
