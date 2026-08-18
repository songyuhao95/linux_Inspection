```json
{
  "ac_map": [
    {
      "ac_id": "AC-1",
      "expected_exit": 0,
      "test_command": "python -m pytest -q tests/test_render_html.py"
    },
    {
      "ac_id": "AC-2",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    }
  ],
  "allowed_tools": [
    "Read",
    "Edit",
    "Write",
    "Bash:test"
  ],
  "checkpoint_rule": "report-on-exit",
  "contract_id": "contract-T-129-v1",
  "contract_sha256": "sha256:5e9cec8d2ca2a22609b07f04ed8938fa74d1a52e57315e05b5ca2b7163674d46",
  "contract_version": 1,
  "cost_required": false,
  "deliverables": [
    {
      "kind": "implementation",
      "path": "inspect/render_html.py",
      "required": true
    },
    {
      "kind": "implementation",
      "path": "inspect/templates/html-report-v1.html",
      "required": true
    },
    {
      "kind": "tests",
      "path": "tests/test_render_html.py",
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
    "reset_hard",
    "clean",
    "secret_access"
  ],
  "forbidden_paths": [
    "run/events.ndjson",
    ".claude/",
    "runtime/",
    "inventory/hosts.local.ini",
    "inspect/render_xlsx.py",
    "inspect/cli.py"
  ],
  "idempotency_key": "T-129-html-flat-metric-card",
  "input_artifacts": [
    {
      "path": "README.md",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/render_html.py",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "inspect/templates/html-report-v1.html",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "tests/test_render_html.py",
      "sha256": "",
      "version": "workspace"
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "保留 data-* 筛选属性和三种预渲染视图；只删除展示冗余字段，不改变事实源"
  ],
  "network_scope": [],
  "non_goals": [
    "不改变事实源 JSON",
    "不在浏览器端重新计算业务汇总",
    "不引入前端依赖",
    "HTML 中不恢复明文 IP，沿用事实源值"
  ],
  "objective": "简化离线 HTML 报表：移除独立主机小卡片和证据/来源展开区，将指标详情统一为 Excel Local 列字段。",
  "output_schema": "task-report",
  "owned_paths": [
    "contracts/contract-T-129-v1.md",
    "inspect/render_html.py",
    "inspect/templates/html-report-v1.html",
    "tests/test_render_html.py"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-report-fixes",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "host-result-v1 JSON schema",
      "Excel renderer",
      "指标采集逻辑"
    ],
    "include": [
      "inspect/render_html.py",
      "inspect/templates/html-report-v1.html",
      "tests/test_render_html.py"
    ]
  },
  "success_definition": "每个按主机视图的大卡片内含主机摘要与指标表；指标只展示 host/ip/metric_id/name/raw_value/normalized_value/unit/status/threshold_rule/command 对应字段；不再渲染证据来源锚点、evidence/provenance 明细或单独宏观卡片；筛选和三种分组仍可用。",
  "task_id": "T-129",
  "timeout_minutes": 45,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-129 HTML 报表卡片简化

## 目标
按用户截图反馈，去掉层级重复和难读的证据来源区，让 HTML 详情与 Excel Local 列字段保持一致。

## 实现要求
- 主机视图中将当前独立的宏观主机小卡片信息合并到对应主机大卡片标题/摘要区域。
- 删除“证据与来源锚点”展开区，以及 threshold/evidence/provenance 的冗余字段；保留可读 `threshold_rule` 和 `command`。
- 指标详情展示 Excel Local 的字段：host、ip、metric_id、name、raw_value、normalized_value、unit、status、threshold_rule、command。
- 三种分组模式、筛选、多选搜索、无指标主机技术失败提示继续工作。
- 更新测试，明确旧证据字段不出现在 HTML 指标详情中。

## 停止规则
不得修改事实源契约或在浏览器端重新聚合业务数据；发现现有报表规格与本合同冲突时停止并报告。
