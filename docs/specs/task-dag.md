# G2 垂直任务 DAG（T-101..T-108）

- 文档 ID：task-dag
- 所属合同：contract-T-002-v1（run-20260814-001 / T-002 / phase=plan）
- 版本：v1（2026-08-15）
- 状态：G2 方案文档（待 G2 批准；DAG 由主会话 tasks.mjs freeze，本任务不自行 freeze）
- 机器输出：run/plans/run-20260814-001-plan.json（本 DAG 的机器可执行子集，结构符合 tasks.mjs freeze 要求）

## 1. 设计原则

1. **垂直切片**：每个任务独立实现、测试、合并；任务内的链路（定义→实现→测试→报告）完整，不跨任务借接口未定义。
2. **写范围互斥**：owned_paths 全局不重叠（tasks.mjs validatePlan 机械校验）；夹具按任务分目录（tests/fixtures/<域>/）。
3. **依赖合法**：depends_on 仅引用已存在任务；无环（DFS 校验）。
4. **每任务可独立验证**：AC 均为可执行命令（测试或文本断言），证据类型来自 evidence_types。
5. 任务合同（contract-T-10x-v1）由主会话在派发前创建并 seal；本 DAG 只声明契约引用与 AC 草案，不 seal 任何合同。

## 2. DAG 总览

```
T-101 CLI 入口与指标注册表 ──▶ T-102 配置层与阈值 override
                                  │
                                  ▼
                              T-103 采集执行层（inventory/ansible/probe）
                                  │
                                  ▼
                              T-104 normalize + host-result-v1 事实源
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
         T-105 stdout        T-106 Excel         T-107 离线 HTML
              └───────────────────┼───────────────────┘
                                  ▼
                              T-108 端到端与本地调试路径
```

- 主链：T-101 → T-102 → T-103 → T-104 →（T-105/T-106/T-107 并行）→ T-108。
- T-105/T-106/T-107 相互独立，可并行派发；T-108 在三者完成后派发。
- 无环；依赖均指向更早任务；写范围两两不相交（§7 校验记录见 docs/reviews/plan-review.md）。

## 3. 通用约定

- **phase**：全部 8 任务为 `implement`。
- **受保护路径（所有任务 forbidden_paths 公共部分）**：`docs/specs/`（G1 六份 + G2 四份，实现任务不得修改方案文档）、`docs/reviews/`、`contracts/`、`run/events.ndjson`、`run/plans/`、`linux-docx/`、`README.md`、`.claude/`。T-108 额外**拥有** `docs/runbook.md`（调试手册）。
- **互斥声明**：owned_paths 全量并集两两不相交（不含重叠前缀文件，仅允许目录边界）；T-101..T-108 各持有自己的 `run/reports/T-10x.md`。
- **证据类型**（contract evidence_types 子集）：`artifact`（文件+sha256）、`documentation-validation`（AC 内容断言/测试）、`structure-review`（模块边界与依赖方向审查）、`git-diff`（受保护路径零改动）。
- **合并顺序**：按 DAG 拓扑序串行集成；冲突无法机械判断→BLOCKED 请求用户决策（worktree-policy）。

## 4. T-101 — CLI 入口与指标注册表

- 目标：inspect.sh 入口、cli.py（argparse、主机选择、退出码 0/2/10/20）、metrics.py 指标注册表（10 个共同 P0 定义：命令/超时/解析器名/单位/来源锚点/阈值规则 ID 引用）、--list-metrics/--info 只读命令、包骨架（pyproject/requirements）。
- depends_on：无
- owned_paths：
  - inspect.sh
  - inspect/__init__.py
  - inspect/cli.py
  - inspect/metrics.py
  - pyproject.toml
  - requirements.txt
  - requirements-dev.txt
  - tests/test_cli.py
  - tests/test_metrics.py
  - tests/fixtures/cli/
  - run/reports/T-101.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余 T-102..T-108 owned_paths 全量（inspect/config.py、inspect/inventory.py、inspect/ansible_runner.py、inspect/probe.py、inspect/normalize.py、inspect/fact_source.py、inspect/render_*.py、inspect/schema/、inspect/templates/、inspect/data/、tests/test_config.py、tests/test_inventory.py、tests/test_ansible_runner.py、tests/test_normalize.py、tests/test_fact_source.py、tests/test_render_*.py、tests/test_e2e.py、tests/fixtures/{config,inventory,raw,json,stdout,xlsx,html,e2e}/、run/reports/T-102..T-108.md）
- AC（草案，正式版以派发时 seal 的合同为准）：
  - AC-1 `bash inspect.sh -h` 帮助含全部选项/退出码表/主机选择示例/脱敏声明（REQ-C-01/05）
  - AC-2 `--list-metrics` 输出 10 个共同 P0 指标 ID；`--info local.cpu.utilization` 含单位与来源锚点（REQ-C-04/REQ-M-*）
  - AC-3 未知选项/`--local` 与 `-H` 互斥/不支持中间件参数→退出码 2（REQ-C-02/03）
  - AC-4 fixture JSON 驱动退出码映射：CRIT+`--fail-on critical`→20；默认→0；JSON 损坏→10（REQ-C-03）
  - AC-5 `python -m pytest tests/test_cli.py tests/test_metrics.py -q` 全绿
  - AC-6 无 `-H`/`-i` 时巡检本机语义（REQ-C-02）
- 证据类型：artifact、documentation-validation、structure-review、git-diff

## 5. T-102 — 配置层与阈值 override

- 目标：config.py（inspect.yml 加载、阈值分层合并：外部配置>文档基线>UNKNOWN、provenance 记录）、文档基线文件 `inspect/data/thresholds/linux-common-p0-v1.yaml`（MR §6 逐项转写，含 source_anchor，禁止发明阈值）、`threshold-override-v1.schema.json` 落盘、override 语法校验。
- depends_on：[T-101]
- owned_paths：
  - inspect/config.py
  - inspect/data/thresholds/linux-common-p0-v1.yaml
  - inspect/schema/threshold-override-v1.schema.json
  - tests/test_config.py
  - tests/fixtures/config/
  - run/reports/T-102.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths（T-101 的 inspect.sh/cli.py/metrics.py 等全量）
- AC（草案）：
  - AC-1 基线文件含 10 个指标且每条带 source_anchor 与 linux-common-p0-v1 版本标识；与 MR §6 数值一致（REQ-D-05/REQ-N-01）
  - AC-2 无 override 时加载文档基线，threshold.layer=document-baseline（REQ-D-05）
  - AC-3 override 文件覆盖基线生效且 provenance.config_sources 记录来源（REQ-D-04/05）
  - AC-4 非法 override（未知 status/op、缺 note、双重判定）被 schema 拒绝（§6 语法）
  - AC-5 `python -m pytest tests/test_config.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff

## 6. T-103 — 采集执行层（inventory / ansible / probe + fixture 注入）

- 目标：inventory.py（-H 生成临时 inventory、-i/--limit/--all 解析）、ansible_runner.py（playbook 生成：gather_facts:false、serial:1、raw/script + `/bin/bash -lc`、最小化 become；执行与结果回传；`INSPECT_FIXTURE_DIR` 调试注入点）、probe.py（能力探测命令与解析）、allow-list 校验、超时注入（15s/10s/15s/300s）、无重试。
- depends_on：[T-102]
- owned_paths：
  - inspect/inventory.py
  - inspect/ansible_runner.py
  - inspect/probe.py
  - tests/test_inventory.py
  - tests/test_ansible_runner.py
  - tests/fixtures/inventory/
  - tests/fixtures/raw/
  - run/reports/T-103.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths
- AC（草案）：
  - AC-1 生成 playbook 文本含 `gather_facts: false`、`serial: 1`、`raw`/`script`、`/bin/bash -lc`（REQ-E-01/02）
  - AC-2 fixture 模式无主机返回预录输出，stderr 声明调试模式（REQ-N-08）
  - AC-3 未登记命令被 allow-list 拒绝（REQ-E-05/REQ-C-06）
  - AC-4 probe 15s、指标 10s（日志 15s）、单主机 300s 注入；超时→TIMEOUT→UNKNOWN；无重试（REQ-E-04/08）
  - AC-5 连接失败→ERROR 无业务结论；部分失败→PARTIAL（REQ-E-07）
  - AC-6 `-H` 生成临时 inventory；`-i --limit`/`--all` 语义（REQ-C-02）
  - AC-7 `python -m pytest tests/test_inventory.py tests/test_ansible_runner.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff（本任务 R2：外部执行环境+权限模型，独立验证触发项，见 risk-register §7）

## 7. T-104 — normalize + host-result-v1 事实源

- 目标：normalize.py（10 指标解析器、脱敏、四状态判定、threshold/provenance 填充）、fact_source.py（原子写 tmp→fsync→rename、汇总索引、不覆盖）、`host-result-v1.schema.json` 落盘、执行/业务状态分离。
- depends_on：[T-103]
- owned_paths：
  - inspect/normalize.py
  - inspect/fact_source.py
  - inspect/schema/host-result-v1.schema.json
  - tests/test_normalize.py
  - tests/test_fact_source.py
  - tests/fixtures/json/
  - run/reports/T-104.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths
- AC（草案）：
  - AC-1 10 指标 fixture→metric 对象必填字段齐备（REQ-D-03）
  - AC-2 事实源 JSON 通过 host-result-v1.schema.json（REQ-D-01/06）
  - AC-3 原子写：无半成品、inspection_id 唯一、重跑不覆盖（REQ-D-06/REQ-N-09）
  - AC-4 执行/业务分离：error 存在→status=UNKNOWN、execution_status=PARTIAL/ERROR（REQ-D-02/REQ-N-03）
  - AC-5 C3/C5/C8 样例→UNKNOWN（layer=unresolved-document-conflict/missing）；外部配置覆盖生效（REQ-D-05）
  - AC-6 脱敏：IP→`<IP>`、凭据不出现在 JSON（REQ-E-09/REQ-N-04）
  - AC-7 `python -m pytest tests/test_normalize.py tests/test_fact_source.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff（R1 持久化 + R3 脱敏，独立验证触发项）

## 8. T-105 — stdout 渲染

- 目标：render_stdout.py（RR §2：run 摘要、主机摘要、失败/未知列表、退出码说明；UNKNOWN/ERROR 显式原因；无颜色环境符号区分）。
- depends_on：[T-104]
- owned_paths：
  - inspect/render_stdout.py
  - tests/test_render_stdout.py
  - tests/fixtures/stdout/
  - run/reports/T-105.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths
- AC（草案）：
  - AC-1 run/主机摘要与状态计数与 JSON 一致（REQ-R-01/08）
  - AC-2 UNKNOWN/ERROR 显式展示原因（missing/conflict/permission/timeout）（REQ-R-02）
  - AC-3 无颜色环境符号区分；四状态映射正确（REQ-R-07）
  - AC-4 渲染不触发采集（mock 断言零执行调用）（REQ-N-06）
  - AC-5 `python -m pytest tests/test_render_stdout.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff

## 9. T-106 — Excel 渲染

- 目标：render_xlsx.py（xlsxwriter；三 Sheet Overview/Local/Errors-Evidence；RR §3 布局；UNKNOWN 不混入 OK 计数；文件名 `<inspection-id>.xlsx`，`--xlsx-out` 覆盖）。
- depends_on：[T-104]
- owned_paths：
  - inspect/render_xlsx.py
  - tests/test_render_xlsx.py
  - tests/fixtures/xlsx/
  - run/reports/T-106.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths
- AC（草案）：
  - AC-1 三 Sheet 存在且列/行内容符合 RR §3（REQ-R-03）
  - AC-2 状态计数与 JSON 一致、UNKNOWN 不混入 OK（REQ-R-03/08）
  - AC-3 xlsxwriter 缺失→明确报错退出码 10（REQ-N-06 负向）
  - AC-4 文件名与 --xlsx-out 覆盖（REQ-R-04）
  - AC-5 `python -m pytest tests/test_render_xlsx.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff

## 10. T-107 — 离线单文件 HTML 渲染

- 目标：render_html.py + 模板 html-report-v1.html（RR §4/§5：全内联 CSS/JS、JSON 内嵌、左导航+右滚动区、四状态色板、打印友好）。
- depends_on：[T-104]
- owned_paths：
  - inspect/render_html.py
  - inspect/templates/html-report-v1.html
  - tests/test_render_html.py
  - tests/fixtures/html/
  - run/reports/T-107.md
- forbidden_paths：公共受保护路径 + `docs/` + 其余任务 owned_paths
- AC（草案）：
  - AC-1 单文件：无 `<link`、无 `<script src`、无 fetch/外链资源（REQ-R-05）
  - AC-2 内嵌 JSON 与事实源一致；四状态过滤可用（REQ-R-05/06）
  - AC-3 色板/徽标符合 RR §5（#2E7D32/#F9A825/#C62828/#757575）（REQ-R-07）
  - AC-4 打印友好：默认宏观摘要（REQ-R-06）
  - AC-5 `python -m pytest tests/test_render_html.py -q` 全绿
- 证据类型：artifact、documentation-validation、structure-review、git-diff

## 11. T-108 — 端到端与本地调试路径

- 目标：tests/test_e2e.py（fixture 全链路：CLI→采集→normalize→JSON→三类报表）、回滚演练、docs/runbook.md（本地调试与兼容矩阵 C1-C8 执行手册）、全量测试复跑。
- depends_on：[T-105, T-106, T-107]（传递依赖 T-101..T-104）
- owned_paths：
  - tests/test_e2e.py
  - tests/fixtures/e2e/
  - docs/runbook.md
  - run/reports/T-108.md
- forbidden_paths：公共受保护路径（`docs/specs/`、`docs/reviews/`、contracts/、run/events.ndjson、run/plans/、linux-docx/、README.md、.claude/）+ 其余任务 owned_paths
- AC（草案）：
  - AC-1 fixture 全链路无目标主机通过，三类报表与事实源计数一致（REQ-R-08/REQ-N-08）
  - AC-2 `bash inspect.sh --local` 本机 smoke：退出码 ∈ {0,10}（无用法错误 2）且事实源 JSON 生成并通过 schema（REQ-N-07）
  - AC-3 回滚演练：重跑生成新 inspection_id、旧 JSON 未被覆盖、旧 JSON 可独立重渲染三类报表（REQ-N-09）
  - AC-4 docs/runbook.md 含兼容矩阵 C1-C8 执行命令与 fixture 使用说明（REQ-N-07/08）
  - AC-5 全量回归：`python -m pytest tests/ -q` 全绿（T-101..T-107 AC 复跑）
- 证据类型：artifact、documentation-validation、structure-review、git-diff（R2/R3 端到端，独立验证触发项）

## 12. freeze 与派发约定

1. 主会话以 `node "C:/Users/SYH/.assembly-development/scripts/tasks.mjs" freeze run-20260814-001 run/plans/run-20260814-001-plan.json` 冻结；validatePlan 机械校验无环、依赖存在、写范围不重叠（本任务已自检，记录于 docs/reviews/plan-review.md）。
2. 派发按 `tasks.mjs ready` 顺序；每个任务独立 worktree，基线=冻结时 baseCommit。
3. 每任务派发前主会话 seal 对应合同 contract-T-10x-v1（以本文件 AC 草案为准修订）。
4. T-105/T-106/T-107 并行派发；T-108 待三者 done。
5. 本任务（T-002）不自行 freeze、不 seal T-10x 合同（forbidden_ops：freeze_dag、modify_gate_state）。

## 13. 与 T-002 交付物关系

- 需求映射：docs/specs/requirements-acceptance-matrix.md（各任务 AC 引用 REQ-* ID）
- 技术依据：docs/specs/technical-design.md（§3 目录布局、§4 模块边界、§5 probe 与解析器、§6 override 语法、§7 JSON Schema、§8 选型、§9 兼容矩阵、§10 调试路径、§11 回滚）
- 风险：docs/specs/risk-register.md（R0-R3，独立验证触发清单 §7）
- 审查：docs/reviews/plan-review.md（本 DAG 的 validatePlan 校验记录）
