# 报表路线图（reporting-roadmap v1）

- 文档 ID：reporting-roadmap
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案；本文件只描述报表契约与路线，不承诺实现细节

## 1. 数据流（唯一事实源）

---
采集（Ansible raw/script）→ normalize → 原子写 host-result-v1 JSON
        ↓（报表只消费 JSON，不二次采集）
  stdout 终端摘要 / Excel 多 Sheet / 离线单文件 HTML
---

- **版本化 JSON 是唯一事实源**：报表阶段只读 JSON；任何报表与事实源不一致时以 JSON 为准。
- 报表之间不允许相互引用非 JSON 数据；不出现在 JSON 中的数据不得出现在报表中。

## 2. stdout 终端输出

- 内容：run/合同摘要、主机摘要（execution_status、各状态计数）、失败/未知指标列表、退出码说明。
- 顺序：先全局，后逐主机；-UNKNOWN- 与 -ERROR- 必须显式展示原因（missing/conflict/permission/timeout）。
- 彩色化可选（四状态颜色与 HTML 一致，见第 5 节）；无颜色环境下以符号/缩写区分。

## 3. Excel 报表（首版 Sheet 规划）

| Sheet | 内容 |
| --- | --- |
| Overview | run 信息、主机×状态汇总、状态计数、阈值版本（linux-common-p0-v1）、生成时间 |
| Local | 每主机每条明细一行：host、ip、metric_id、name、raw_value、normalized_value、unit、status、清晰 threshold_rule、command；系统负载按 1/5/15 分钟展开，磁盘/inode 按挂载点展开 |
| Errors-Evidence | 所有 error 非空的指标与主机：error.code、message、command、output_summary；以及文档冲突/缺失导致的 UNKNOWN 清单 |

- 首版三 Sheet（Overview / Local / Errors-Evidence），后续按产品 profile 增加 Sheet。
- 文件名：`<inspection-id>.xlsx`（`--excel PATH` 可覆盖路径）。
- Local Sheet 不聚合多值指标：负载的 1 分钟、5 分钟、15 分钟分别成行；磁盘使用率和 inode 使用率按每个挂载点分别成行。每行的 command 仅用于运维复现，报表渲染不执行该命令。

## 4. HTML 报表（离线单文件）

- **离线单文件**：HTML、CSS、JS 全部内联，无外部依赖，可离线打开；数据以 JSON 内嵌于页面（只读，展示层不做二次计算）。
- 布局：
  - 左导航提供主机列表、状态筛选（OK/WARN/CRIT/UNKNOWN）、中间件、监控指标筛选；四者均为原生隐藏下拉框，内含搜索输入和 checkbox 多选，选项超过 10 个时在框内滚动。
  - 正文最上方展示完整 Run 摘要（run_id、inspection_id、主机/指标计数、状态合计、技术失败、执行状态分布、采集时间、生成时间和整体结论）。
  - 摘要下方提供四种正文显示方式：按主机分组、按状态分组、按中间件分组、按监控指标分组；按主机分组时，主机状态摘要与指标明细合并在同一主机大卡片中。指标卡片纵向单列并占满正文宽度。
  - 指标卡片与 Excel Local 列保持一致：host、ip、metric_id、name、raw_value、normalized_value、unit、status、threshold_rule、command；不再展示证据来源锚点、evidence_summary、provenance、error 等扩展块。
- 交互：按状态/主机/中间件/监控指标多选过滤，筛选项支持搜索和滚动；分组视图切换只做静态片段显隐，不在浏览器重新计算业务汇总。
- 打印友好：默认打印当前分组摘要，勾选后打印当前分组详情。
- HTML 安全与可见性约束：内嵌 JSON 将 `<` 编码为 `\u003c` 防止大小写脚本闭合绕过；无指标的 ERROR/PARTIAL 主机必须保留主机级技术失败提示；清除筛选同时清空搜索词并恢复全部选项。

## 5. 四状态与颜色

| status | 语义 | 颜色建议（可配置） | 徽标 |
| --- | --- | --- | --- |
| OK | 正常 | 绿 #2E7D32 | OK |
| WARN | 关注 | 黄/琥珀 #F9A825 | WARN |
| CRIT | 告警/故障 | 红 #C62828 | CRIT（fault 高亮） |
| UNKNOWN | 无规则/冲突/权限/缺失 | 灰 #757575 | UNKNOWN |

- -execution_status-（SUCCESS/PARTIAL/ERROR）以徽标区分于业务状态，避免混淆（如 PARTIAL 灰黄边框 + 业务状态彩色填充）。

## 6. 一致性要求

1. 所有报表由同一份 JSON 渲染；同一 inspection 的三类报表状态计数必须一致。
2. -UNKNOWN- 必须在报表中可见（不得静默过滤）；-ERROR-/技术失败必须可见（Errors-Evidence）。
3. Local Sheet 的 threshold_rule 使用可读中文解释，command 保留事实源中的指标取值命令；source_anchor/evidence_summary/provenance 不作为 Local Sheet 或 HTML 正文列重复展示。
4. host-result-v1 JSON 继续按脱敏契约保存 `<IP>`。Excel Local Sheet 是经 CLI inventory 解析得到的运维展示例外：运行时将 inventory 中的 ansible_host 映射到 ip 列，但不回写 JSON、事件或 HTML 事实源；凭据仍不进入任何报表。

## 7. 路线（后续版本，非本合同交付）

1. **local 垂直切片**（G1/G2 目标）：stdout + Excel 三 Sheet + 离线单文件 HTML 全链路打通。
2. 中间件 profile 指标入 JSON 后，Excel/HTML 按 profile 分 Sheet/分组展示。
3. 趋势/历史对比（读取历史 JSON 事实源）、导出 csv、自定义色板与徽标配置。
4. 仪表盘接入（assembly-development 的 dashboard-start 工具仅用于流水线本身，与本报表路线相互独立）。
