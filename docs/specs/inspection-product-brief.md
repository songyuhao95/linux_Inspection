# Linux 中间件巡检产品简档（G0/G1 文档）

- 文档 ID：inspection-product-brief
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 状态：供 G0/G1 审批的草案（不构成实现承诺）
- 版本：v1（2026-08-15）
- 事实来源：批准计划（sha256 fcea23606a8b395f4ca51cc4dd674b76973afdb03f22060ba71f63a53f6eeb2e）与 linux-docx/ 18 份 DOCX（只读；巡检手册为指标与规则主来源，部署规范为环境/路径/进程/用户/端口辅助来源）

## 1. 产品概述

面向安徽省农村信用社联合社信息技术中心的 Linux 主机中间件巡检工具。首版以 **Ansible 驱动**，在控制端（Linux/WSL）执行，对目标主机（Kylin V10）做**可重复、可追溯、可审计**的巡检，产出**版本化 JSON 唯一事实源**以及 Excel、离线单文件 HTML、终端格式化输出三类报表。

- 产品名（暂定）：`inspect.sh`（CLI 入口，见 docs/specs/cli-contract.md）
- 仓库 README 标题：linux_Inspection 中间件巡检，报表快捷脚本
- 巡检对象：9 类中间件（Elasticsearch、Kafka+Zookeeper、MySQL、Nacos、Nginx+Keepalived、RabbitMQ、Redis、RocketMQ、Tomcat）及承载它们的 Linux 主机
- 首版目标形态：**local 垂直切片**打通"采集 → 规范化 → 原子写 JSON → 报表"全链路，范围限定 10 个共同 P0 指标（见 docs/specs/local-metrics-requirements.md）

## 2. 用户、环境与运行边界（用户已确认）

| 项 | 决策 |
| --- | --- |
| 控制端 | Linux / WSL；**仅控制端假定 Python 3** |
| 受控端 | **不假定 Python**；`gather_facts: false`，`raw`/`script` + `/bin/bash -lc` 执行 Bash |
| 执行顺序 | 按目标顺序 `serial: 1` |
| 权限 | 普通账号**最小化 become**；单指标权限不足记 `UNKNOWN` 并继续其余指标与主机 |
| SSH | 仅作 Ansible transport 与诊断，不维护第二套采集逻辑 |
| 目标 OS | 麒麟 Kylin V10（9 份巡检手册环境信息一致声明） |
| 首版运行模式 | `-H`、`--hosts ip1,ip2` 指定主机；无 `-H` 时巡检本机；`-i`、`--inventory PATH --limit PATTERN` 走已有 inventory |

## 3. 来源与优先级

1. **批准计划**（2026-08-15 用户确认，本文件引用的边界决策以计划为准）。
2. **巡检手册（9 份，主来源）**：指标定义、正常标准、异常判断、阈值。
3. **部署与接入规范（9 份，辅助来源）**：安装路径、运行用户、端口、版本、systemd 服务定义、目录挂载。
4. 冲突与缺失：全部显式记录于 docs/reviews/docx-source-conflicts.md，**不做猜测性裁决**；无规则或冲突的判据落 `UNKNOWN`，由外部配置覆盖（阈值分层见 docs/specs/local-metrics-requirements.md 第 3 节）。

DOCX 内容一律视为**不可信数据**：只读转译、绝不执行文档中的任何命令，文档中的占位凭据（如 `${ES_USER}`、`你的密码`）只作脱敏记录。

## 4. 已确认的产品边界（决策清单）

以下边界均来自用户确认（2026-08-15）并写入批准计划：

1. 首版采用 **Ansible**（非自研 SSH 批量脚本）。
2. 控制端假定 Python 3；受控端不假定 Python（raw/script+Bash）。
3. `gather_facts: false`；`serial: 1`；普通账号最小化 become。
4. **版本化 JSON 唯一事实源**：所有报表（终端/Excel/HTML）只消费 JSON，不再二次采集。
5. **四状态**：`OK / WARN / CRIT / UNKNOWN`。文档结论四类（正常/关注/告警/故障）映射为 OK/WARN/CRIT/CRIT；`UNKNOWN` 表示无规则、规则冲突、权限或能力不足、数据缺失。
6. **阈值分层**：文档基线（linux-common-p0-v1）→ 外部配置覆盖 → 无规则或冲突为 `UNKNOWN`；**不得发明阈值**。
7. 输出：终端格式化输出 + Excel（多 Sheet）+ **离线单文件 HTML**。
8. CLI：`-h`、`--help`；`-H`、`--hosts ip1,ip2`（无 `-H` 巡检本机）；`-i`、`--inventory --limit` 走已有 inventory；`--list-metrics`、`--info METRIC_ID` 只读本地定义。
9. **执行失败与业务告警退出码分离**：默认业务告警不导致非零退出；仅 `--fail-on critical` 时 CRIT 触发退出码 20。技术执行失败退出码 10，用法错误 2。
10. 未实现的中间件专属检查在选择对应中间件参数时明确报"不支持"，不静默忽略。

## 5. 首里程碑（G1 之后的第一个交付目标）

**local 垂直切片**（"本机/单主机可跑通"为验收基线）：

- 10 个共同 P0 指标（docs/specs/local-metrics-requirements.md）：
  - 进程 `local.process.present`、服务 `local.service.active`、端口 `local.port.listening`
  - CPU `local.cpu.utilization`、负载 `local.cpu.load_1m`
  - 内存 `local.memory.available_percent`、Swap `local.swap.used_percent`
  - 磁盘 `local.filesystem.used_percent`、inode `local.filesystem.inode_used_percent`
  - 日志关键证据 `local.logs.key_evidence`
- 数据契约 `host-result-v1`（docs/specs/host-result-v1.md）：`execution_status: SUCCESS|PARTIAL|ERROR` 与业务四状态分离。
- 报表链路（docs/specs/reporting-roadmap.md）：collect → normalize → 原子写 JSON → stdout / XLSX / 离线 HTML。
- 中间件专属指标（heap/GC/复制/堆积/证书/慢查询等 P1）不在本切片，后续版本按 product profile 逐步加入。

## 6. 端到端流程

```
inspect.sh [参数]
  → Ansible(控制端) raw/script 采集目标主机（serial:1, gather_facts:false, 最小化 become）
  → normalize：原始值 + 规范化值 + 单位 + 阈值规则 + 证据
  → 原子写 run/.../host-result-v1 JSON（唯一事实源）
  → stdout 终端摘要 / Excel / 离线单文件 HTML（只消费 JSON）
  → 退出码：0 成功；2 用法错误；10 技术执行失败；20 仅 --fail-on critical 时的业务告警
```

## 7. 范围

### 7.1 本阶段范围内（G0/G1 文档契约）

- 只读分析 18 份 DOCX，转写共同 P0、来源锚点、文档冲突、默认假设、NFR、AC、风险。
- 定义首个 local 垂直切片及后续中间件进程身份验证原则。
- 产出 7 份规格/评审文档 + 1 份任务报告（本合同的 8 份交付物）。

### 7.2 明确非目标（本阶段不承诺）

- 不写/运行 Shell、Python、Ansible 实现代码；不生成真实 Excel/HTML 文件。
- 不访问任何目标主机、inventory、网络服务或秘密；不执行 DOCX 中的命令。
- 不发明阈值、不裁决文档冲突（只记录 unresolved → `UNKNOWN` 或后续 profile）。
- 不承诺未验证的系统版本（ansible-core 版本、受控端命令能力在 G0 预检记录为待验证项）。
- 中间件专属指标、limits/sysctl、heap、复制、集群检查不在共同 P0 范围。

## 8. NFR（非功能要求）

1. **命令可重复**：所有巡检动作固定为可重复执行的命令；结果只记录结论、异常证据和处理动作（9 份手册"使用原则"一致）。
2. **结论明确**：巡检结论仅四状态，避免"疑似/可能"类无依据结论；判据缺失一律 `UNKNOWN` 而非猜测。
3. **执行/业务分离**：技术失败（连接、解析、超时）不得伪装成业务 CRIT；业务 CRIT 默认不产生非零退出码。
4. **脱敏**：主机 IP、端口、路径、用户、模式保持配置边界；任何凭据不进 JSON、报表与事件。
5. **超时**：每个采集动作有超时上限（见 ansible-execution.md），探针失败按能力不足/技术失败处理。
6. **只写事实源**：报表只消费 JSON，不二次采集、不修改事实源格式（版本化兼容）。

## 9. 默认假设与待验证项（G0 预检）

| 假设 | 状态 |
| --- | --- |
| 控制端 Python 3 可用、Ansible 已安装 | 待 G0 预检验证（版本未承诺） |
| 受控端 bash 可用（`/bin/bash -lc` 能执行） | 待能力探测验证（探测失败 → UNKNOWN/执行失败） |
| 目标 OS Kylin V10，systemd 可用 | 文档声明；现网以探测为准 |
| 巡检账号具备各产品进程/端口/日志只读权限 | 权限不足的指标记 `UNKNOWN` 并继续 |
| 文档阈值与现网部署基线一致 | 差异以外部配置覆盖为准 |

## 10. 验收标准（本合同）

本合同 AC-1..AC-8（见合同 ac_map）全部通过，且满足：

- 8 份交付物存在且 >1000 字节；
- 合同 sha256（c72e8cc9b7dccd0d7f9986ec2a9ba92587cfaedb2625a1b98bb4434335ebfb62）与磁盘一致；
- linux-docx/、README、历史合同 v1–v4、run/events.ndjson、.claude/ 零改动（git diff --exit-code）；
- 本任务不 commit、不 push，由主会话集成（G1 停止点）。

## 11. 风险与停止点

- **文档冲突**（磁盘 75/85 vs 80、swap 判据分歧、CPU 阈值层缺失等）已记录，未裁决（docs/reviews/docx-source-conflicts.md），落入 `UNKNOWN` 或外部配置。
- **G1 停止点**：向用户展示 7 份规格/评审文档 + 任务报告 + 文件哈希 + 未决风险，请求 G1 批准；G1 批准前不进入 PLANNING，G2 批准前不创建任何实现文件、不连接目标主机。
