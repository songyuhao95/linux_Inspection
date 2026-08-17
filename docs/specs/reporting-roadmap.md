# 报表路线图（reporting-roadmap v1）

- 文档 ID：reporting-roadmap
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案；本文件只描述报表契约与路线，不承诺实现细节

## 1. 数据流（唯一事实源）

```
采集（Ansible raw/script）→ normalize → 原子写 host-result-v1 JSON
        ↓（报表只消费 JSON，不二次采集）
  stdout 终端摘要 / Excel 多 Sheet / 离线单文件 HTML
```

- **版本化 JSON 是唯一事实源**：报表阶段只读 JSON；任何报表与事实源不一致时以 JSON 为准。
- 报表之间不允许相互引用非 JSON 数据；不出现在 JSON 中的数据不得出现在报表中。

## 2. stdout 终端输出

- 内容：run/合同摘要、主机摘要（execution_status、各状态计数）、失败/未知指标列表、退出码说明。
- 顺序：先全局，后逐主机；`UNKNOWN` 与 `ERROR` 必须显式展示原因（missing/conflict/permission/timeout）。
- 彩色化可选（四状态颜色与 HTML 一致，见第 5 节）；无颜色环境下以符号/缩写区分。

## 3. Excel 报表（首版 Sheet 规划）

| Sheet | 内容 |
| --- | --- |
| Overview | run 信息、主机×状态汇总、状态计数、阈值版本（linux-common-p0-v1）、生成时间 |
| Local | 每主机每指标一行：metric_id、raw_value、normalized_value、unit、status、threshold 规则、来源锚点、evidence 摘要、provenance |
| Errors-Evidence | 所有 error 非空的指标与主机：error.code、message、command、output_summary；以及文档冲突/缺失导致的 UNKNOWN 清单 |

- 首版三 Sheet（Overview / Local / Errors-Evidence），后续按产品 profile 增加 Sheet。
- 状态以文字+背景色呈现（第 5 节色板）；`UNKNOWN` 不混入 OK 计数。
- 文件名：`<inspection-id>.xlsx`（`--xlsx-out` 可覆盖路径）。

## 4. HTML 报表（离线单文件）

- **离线单文件**：HTML、CSS、JS 全部内联，无外部依赖，可离线打开；数据以 JSON 内嵌于页面（只读，展示层不做二次计算）。
- 布局：
  - 左导航：run 摘要、主机列表、状态筛选（OK/WARN/CRIT/UNKNOWN）、指标维度。
  - 右滚动区：宏观卡片（每主机四状态计数、execution_status 徽标、整体结论）→ 主机详情（逐指标卡片：raw/normalized/unit/status/threshold/evidence/error/provenance）。
- 交互：按状态/主机/指标过滤；点击指标卡片展开证据与来源锚点。
- 打印友好：默认打印宏观摘要，详情可展开。

## 5. 四状态与颜色

| status | 语义 | 颜色建议（可配置） | 徽标 |
| --- | --- | --- | --- |
| OK | 正常 | 绿 #2E7D32 | OK |
| WARN | 关注 | 黄/琥珀 #F9A825 | WARN |
| CRIT | 告警/故障 | 红 #C62828 | CRIT（fault 高亮） |
| UNKNOWN | 无规则/冲突/权限/缺失 | 灰 #757575 | UNKNOWN |

- `execution_status`（SUCCESS/PARTIAL/ERROR）以徽标区分于业务状态，避免混淆（如 PARTIAL 灰黄边框 + 业务状态彩色填充）。

## 6. 一致性要求

1. 所有报表由同一份 JSON 渲染；同一 inspection 的三类报表状态计数必须一致。
2. `UNKNOWN` 必须在报表中可见（不得静默过滤）；`ERROR`/技术失败必须可见（Errors-Evidence）。
3. 阈值规则与来源锚点随指标展示，便于审计（对应 evidence_types 的 source-traceability）。
4. 报表不含凭据与明文 IP；脱敏规则同 host-result-v1.md 第 3 节。

## 7. 路线（后续版本，非本合同交付）

1. **local 垂直切片**（G1/G2 目标）：stdout + Excel 三 Sheet + 离线单文件 HTML 全链路打通。
2. 中间件 profile 指标入 JSON 后，Excel/HTML 按 profile 分 Sheet/分组展示。
3. 趋势/历史对比（读取历史 JSON 事实源）、导出 csv、自定义色板与徽标配置。
4. 仪表盘接入（assembly-development 的 dashboard-start 工具仅用于流水线本身，与本报表路线相互独立）。
