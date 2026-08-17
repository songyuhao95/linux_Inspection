# G2 方案审查（plan-review）

- 文档 ID：plan-review
- 所属合同：contract-T-002-v1（run-20260814-001 / T-002 / phase=plan）
- 版本：v1（2026-08-15）
- 状态：G2 方案自审查（待 G2 批准；本审查不替代用户 G2 批准，不替代主会话 freeze 与独立验证）
- 审查对象：docs/specs/requirements-acceptance-matrix.md、docs/specs/technical-design.md、docs/specs/risk-register.md、docs/specs/task-dag.md、run/plans/run-20260814-001-plan.json

## 1. 审查范围与方法

| 项 | 方法 | 结果 |
| --- | --- | --- |
| G1 一致性 | 逐项对照 7 份 G1 文档（PB/MR/HR/CC/AE/RR/DC）核验 G2 冻结项来源锚点 | 全部冻结项可回溯（§3） |
| 需求覆盖 | 对照合同必需步骤 3 的 9 个方案覆盖点逐条核对 | 全部覆盖（§4） |
| DAG 机械校验 | 官方 tasks.mjs validatePlan 对 plan.json 执行 | ok=true，无环、无重叠（§5） |
| AC 可执行性 | 合同 AC-1..AC-5 实跑 | 5/5 PASS（§6） |
| 阈值纪律 | 方案中所有判定边界对照 MR §6 汇总表与 DC C1–C13；无发明阈值 | 无未锚定阈值（§7） |

## 2. 输入验证

| 输入 | 验证方式 | 结果 |
| --- | --- | --- |
| 合同 contract-T-002-v1 | `node contract.mjs validate contract-T-002-v1` | ok：v1 sha256:bd4f2237e06af17287d5279a0449e8b2af9111b57ea5ff2e8255eb3897d43888（与合同声明一致） |
| 7 份 G1 文档 | 实测 sha256 对照合同 input_artifacts | 7/7 一致（0770f832...、2c85f63b...、fb101b1c...、172315fc...、3dc03751...、359ddd6c...、fdedac80...） |
| G1 批准记录 | run/events.ndjson gate.approved（G1 artifact 0770f832... by human） | 确认批准事件存在 |

## 3. G2 冻结项与 G1 来源一致性

| 冻结项 | 决策 | G1 来源 | 一致性判定 |
| --- | --- | --- | --- |
| 目录布局 | 仓库根：inspect.sh + inspect/ 包 + tests/ + out/ + .runtime/；事实源 out/<insp>/hosts/ | AE §2；HR §5 | 一致（HR §5 命名/目录属配置边界，未承诺路径） |
| 模块边界 | cli→config/inventory/ansible_runner→normalize→fact_source→renderers 单向 | AE §2 执行模型；RR §1 数据流 | 一致 |
| 采集执行 | raw/script + /bin/bash -lc、gather_facts:false、serial:1、最小化 become、allow-list、不重试、超时 15s/10s/15s/300s | AE §1/§3/§4/§5/§7 | 一致 |
| probe 命令与解析器 | 11 命令能力探测 + 10 指标解析器表 | AE §3；MR §5 | 一致 |
| 阈值 override 语法 | thresholds-override.yml（status/op/value 或 range + note 必填），schema 校验 | MR §3 阈值分层；HR §4 判定顺序 | 一致（外部配置>文档基线>UNKNOWN） |
| 机器可执行 JSON Schema | host-result-v1 + threshold-override-v1（draft-07，随包落盘） | HR §2/§3 | 一致（字段/枚举/必填项与 HR 对齐） |
| Excel/HTML 选型 | xlsxwriter（运行时）；HTML 零库 stdlib+模板内联；stdout stdlib | RR §3/§4/§5 | 一致（三 Sheet、离线单文件、四状态色板） |
| 兼容测试矩阵 | C1-C8：本地（--local/fixture）先行，Kylin 远程待现场；版本项标 G0 预检 | PB §2/§9；AE §8 | 一致（无版本承诺） |
| 本地调试路径 | --local 自巡检 + INSPECT_FIXTURE_DIR fixture 模式 + 单元/e2e + mock inventory | PB §5；CC §3 | 一致（调试模式非用户 CLI） |
| 回滚 | 事实源不可变 + 报表重渲染 + 配置 git revert + 版本回退 + 受控端零修改面 | HR §5/§6；AE §4.4 | 一致 |

## 4. 合同覆盖核对（必需步骤 3 的 9 个方案覆盖点）

| 覆盖点 | 位置 | 状态 |
| --- | --- | --- |
| 目录布局 | technical-design §3 | 覆盖 |
| 模块边界（CLI 解析/Ansible 执行/normalize/JSON 事实源/stdout-Excel-HTML 渲染器） | technical-design §4 | 覆盖 |
| 10 个共同 P0 指标的 probe 命令与解析器 | technical-design §5 | 覆盖 |
| 阈值 override 文件语法 | technical-design §6 | 覆盖 |
| 机器可执行 JSON Schema | technical-design §7（两份 draft-07 全文） | 覆盖 |
| Excel/HTML 库与模板选型（离线单文件约束） | technical-design §8 | 覆盖 |
| 兼容测试矩阵（Kylin V10 + 控制端 Linux/WSL） | technical-design §9 | 覆盖 |
| 本地无目标主机时的调试路径 | technical-design §10 | 覆盖 |
| 回滚方案 | technical-design §11 | 覆盖 |

## 5. DAG 机械校验（官方 validatePlan 实跑）

输入：`node --input-type=module` 导入 tasks.mjs validatePlan 作用于 run/plans/run-20260814-001-plan.json（只校验，未调用 freeze，未写 run/tasks/）。

实际输出：

```
validatePlan.ok = true
validatePlan.errors = []
task count = 8
task ids = T-101,T-102,T-103,T-104,T-105,T-106,T-107,T-108
dependsOn map = {"T-101":[],"T-102":["T-101"],"T-103":["T-102"],"T-104":["T-103"],
  "T-105":["T-104"],"T-106":["T-104"],"T-107":["T-104"],"T-108":["T-105","T-106","T-107"]}
```

结论：
- 无环（DFS 三色通过）；依赖全部存在；8 个任务 ID 唯一；phase=implement 合法。
- 写范围零重叠：owned_paths 并集两两不相交（夹具按 tests/fixtures/<域>/ 分目录）。
- plan.json 结构符合 tasks.mjs freeze 输入要求（tasks 含 id/contractId/dependsOn/phase/ownedPaths/acceptance）；freeze 由主会话执行，本任务未 freeze。

## 6. 合同 AC 实跑记录（T-002 验收）

| AC | 预期退出码 | 实际退出码 | 结论 |
| --- | --- | --- | --- |
| AC-1 六份交付物存在且 >1000 字节 | 0 | 0 | PASS |
| AC-2 需求矩阵含 10 指标与 4 文档引用 | 0 | 0 | PASS |
| AC-3 技术设计含 9 个关键术语 | 0 | 0 | PASS |
| AC-4 任务 DAG 含 T-101..T-108 | 0 | 0 | PASS |
| AC-5 受保护路径 git diff 为空 | 0 | 0 | PASS |

完整输入/证据见 §8 与任务报告（AC 全量命令同合同 ac_map）。

## 7. 阈值纪律与未决项

1. **无发明阈值**：technical-design §5/§6 中所有数值边界均来自 MR §6 汇总表（75/85/95、80、70/80/90、20/10、80、load≤核数等）；override 示例值仅演示语法，标注"值由现场提供/需现场确认"。
2. **unresolved 冲突不裁决**：C3（swap>0）、C5（load/inode 缺失）、C8（unit 命名）在设计中保持 UNKNOWN 语义，仅提供外部配置覆盖入口（technical-design §6.2）。
3. **未决项（转 G2 审批/现场）**：ansible-core/Python/xlsxwriter 版本（G0 预检）、become 方式与 SSH 参数（现场）、override 覆盖值（现场）、夹具真实样本回填（实现期）。以上在 technical-design §12 与 risk-register 中显式标注，均未写成承诺。
4. **本审查不替代**：用户 G2 批准（manual_gate_required）、主会话 freeze 复验、R2/R3 任务独立验证（risk-register §7）。

## 8. 结论

方案与 G1 文档无冲突；DAG 无环、依赖合法、写范围不重叠；AC-1..AC-5 实跑全过。审查判定：**PASS（附带条件）**——条件为本节 §7 未决项须经 G2 批准或 G0 预检/现场确认后方可视为冻结承诺；触发条件见 §7。
