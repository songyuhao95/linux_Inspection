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
      "test_command": "python -m pytest -q tests/test_render_html.py"
    },
    {
      "ac_id": "AC-3",
      "expected_exit": 0,
      "test_command": "python -m compileall -q inspect"
    },
    {
      "ac_id": "AC-4",
      "expected_exit": 0,
      "test_command": "bash inspect.sh --local --html out/html-ui-smoke.html"
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
  "contract_id": "contract-T-127-v1",
  "contract_sha256": "sha256:108694476499d41767e8c1fcee54bfeb3a40f717317b0c835e93c10d85f51f90",
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
    },
    {
      "kind": "documentation",
      "path": "docs/specs/reporting-roadmap.md",
      "required": true
    }
  ],
  "depends_on": [],
  "dfm_required": false,
  "evidence_types": [
    "test-result",
    "diff",
    "vm-smoke"
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
    "out/",
    "inventory/hosts.local.ini",
    "runtime/"
  ],
  "idempotency_key": "T-127-html-ui",
  "input_artifacts": [
    {
      "path": "README.md",
      "sha256": "",
      "version": "workspace"
    },
    {
      "path": "docs/specs/host-result-v1.md",
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
    }
  ],
  "manual_gate_required": false,
  "max_attempts": 2,
  "mitigations": [
    "保持展示层只做显隐和分组视图切换",
    "所有动态文本继续 HTML 转义",
    "不触碰既有运行时/事实源文件"
  ],
  "network_scope": [
    "origin git push only after local verification"
  ],
  "non_goals": [
    "不改变事实源 JSON 契约",
    "不在浏览器端重新计算业务汇总",
    "不引入第三方前端依赖"
  ],
  "objective": "改造离线 HTML 报表交互布局：将 Run 摘要置于正文顶部，左侧提供主机/状态/中间件多选搜索筛选，并支持按主机、状态、中间件三种方式分组展示。",
  "output_schema": "task-report",
  "owned_paths": [
    "contracts/contract-T-127-v1.md",
    "inspect/render_html.py",
    "inspect/templates/html-report-v1.html",
    "tests/test_render_html.py",
    "docs/specs/reporting-roadmap.md"
  ],
  "parent_task_id": null,
  "phase": "implement",
  "risk_level": "medium",
  "run_id": "run-20260818-html-ui",
  "schemaVersion": 1,
  "scope": {
    "exclude": [
      "业务指标采集逻辑",
      "Excel 报表逻辑",
      "外部网络资源"
    ],
    "include": [
      "inspect/render_html.py",
      "inspect/templates/html-report-v1.html",
      "tests/test_render_html.py",
      "docs/specs/reporting-roadmap.md"
    ]
  },
  "success_definition": "HTML 报表仍为零外链单文件，静态消费事实源；摘要显示在正文顶部；三类多选筛选与搜索框可用；三种分组视图可切换；测试、自检和真实虚拟机 HTML 生成验证通过。",
  "task_id": "T-127",
  "timeout_minutes": 45,
  "triggers": [],
  "verification_required": true,
  "worktree": null
}

```

# T-127 HTML 报表交互改造

## 目标
按用户需求改造离线单文件 HTML 报表的布局和筛选交互，不改变 host-result-v1 事实源契约及业务指标语义。

## 实现要求
- Run 摘要全部移动到正文最上方。
- 左侧仅保留主机列表、状态筛选、中间件筛选；三者都使用可展开/收起的下拉容器、搜索输入和复选框多选。
- 正文摘要下方增加三选一分组模式：按主机、按状态、按中间件。
- 分组内容由渲染期静态生成，浏览器 JavaScript 仅进行筛选显隐与视图切换，不重新聚合指标。
- 继续保证全内联零外链与动态文本转义。

## 验收
以合同 frontmatter 的 AC-1 至 AC-4 为准；同时更新单元测试和 reporting-roadmap 文档。

## 停止规则
发现现有契约或开发文档与本合同冲突时停止并报告，不得静默改变事实源契约或扩大范围。

