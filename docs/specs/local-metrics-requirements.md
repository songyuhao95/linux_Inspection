# 共同 P0 指标需求矩阵（linux-common-p0-v1）

- 文档 ID：local-metrics-requirements
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 来源：9 份巡检手册（主来源）+ 9 份部署规范（辅助来源）；批准计划阈值口径：CPU>80 关注、>90 需附加业务证据；可用内存 <10 告警；swap 0 为基线；磁盘 75/85/95 分层；inode<80；缺失边界显式 unresolved。

## 1. 范围

本文件定义首个 **local 垂直切片** 的 10 个共同 P0 指标（主机级通用指标，适用于全部 9 类中间件产品）。中间件专属指标（heap/GC/复制/堆积/证书/慢查询/limits/sysctl 等）不属于本切片，后续版本按 product profile 逐步加入；进程限制类指标（nofile/nproc 等）另行规划，不在本切片。

## 2. 指标通用字段

每个指标必须记录以下字段；字段缺失即该指标定义不完整，巡检结果不得进入业务判定（落 `UNKNOWN` 并附原因）：

| 字段 | 说明 |
| --- | --- |
| metric_id | 版本化标识，如 `local.cpu.utilization` |
| 数据源 | 采集命令/数据来源（来自手册"巡检命令"列，只读转译，不执行） |
| 计算/采样 | 数值如何计算、采样次数与间隔、聚合方式 |
| 单位 | 如 %、秒、个数 |
| 来源锚点 | 文件名 + 文档类型（巡检手册/部署规范）+ 章节 + 表格位置（表T#R#）+ 文件 sha256 前 8 位 |
| 阈值层 | 该指标适用的阈值分层（文档基线 / 外部配置覆盖 / 无规则为 UNKNOWN） |
| 适用条件 | 模式/角色/版本条件（如 Redis 单机/哨兵/Cluster、Kafka 9093/9092） |
| 权限/能力失败 | 无权限、命令不存在、超时时的处理（一律 `UNKNOWN` 并继续其余指标与主机） |
| 超时 | 采集动作超时上限 |
| 证据 | 必须记录的证据（命令、原始输出摘要、文件路径） |
| 脱敏 | 输出中必须脱敏的内容（IP、凭据、路径按配置边界） |

## 3. 阈值分层规则（用户已确认）

1. **文档基线层**：本文件"文档基线"列，来自巡检手册一致口径；版本标识 `linux-common-p0-v1`。
2. **外部配置覆盖层**：inventory/外部配置按指标提供阈值时，外部配置优先于文档基线；配置来源必须记录在 `provenance`。
3. **无规则/冲突层**：文档未定义边界、或文档间冲突未解决（见 docs/reviews/docx-source-conflicts.md）时，该边界默认 `UNKNOWN`，等待外部配置或 G1/G2 审批决策。**禁止发明阈值**；任何阈值必须可回溯到文档锚点或已批准的外部配置。

## 4. 状态映射（用户已确认）

巡检手册"使用原则/巡检记录模板"定义的结论四类：正常、关注、告警、故障。映射：

| 文档结论 | 产品状态 | 说明 |
| --- | --- | --- |
| 正常 | OK | 全部正常标准满足 |
| 关注 | WARN | 存在隐患，需跟踪 |
| 告警 | CRIT | 影响可用性/容量风险 |
| 故障 | CRIT | 不可用；与告警同为 CRIT（优先级标注：fault > alert） |
| （无） | UNKNOWN | 无规则、规则冲突、权限/能力不足、数据缺失；不属于文档四类 |

技术执行失败（连接失败、命令超时、解析失败）属于 `execution_status`（SUCCESS/PARTIAL/ERROR）层面，**不得**伪装为业务 CRIT（见 docs/specs/host-result-v1.md）。

## 5. 指标定义

### 5.1 local.process.present — 进程存在性

| 字段 | 内容 |
| --- | --- |
| 数据源 | `pgrep`/`ps` 按产品 profile 的进程名或命令行模式匹配（手册"巡检命令"列：如 `pgrep -fa 'kafka.Kafka'`、`ps -ef \| grep '[o]rg.apache.catalina.startup.Bootstrap'`） |
| 计算/采样 | 每目标一次匹配；不匹配即进程缺失 |
| 单位 | 布尔（present/absent）+ 匹配行数 |
| 来源锚点 | 9 份巡检手册 §三(二)P0 必看指标 服务/进程行（如 Kafka 手册 T5R2、Tomcat 手册 T5R1、Redis 手册 T5R1） |
| 阈值层 | 文档基线（进程存在=正常）+ 外部配置（进程模式）覆盖；无 profile 无配置 → UNKNOWN |
| 适用条件 | 产品 profile 提供进程身份（命令模式）；中间件专属进程模式后续版本补齐 |
| 权限/能力失败 | 无权限或 `pgrep` 不可用 → UNKNOWN，继续其余指标 |
| 超时 | 10s |
| 证据 | 命令、匹配行摘要（进程名、PID、启动参数已脱敏） |
| 脱敏 | PID、命令行中的路径参数按配置边界处理 |
| 文档基线 | 进程存在 → OK；进程不存在 → CRIT（故障）；服务反复重启 → WARN |

### 5.2 local.service.active — systemd 服务状态

| 字段 | 内容 |
| --- | --- |
| 数据源 | `systemctl is-active <unit>` / `systemctl show -p ActiveState`（unit 名来自部署规范：mysqld、redis、redis-sentinel、rabbitmq、rocketmq-namesrv、rocketmq-broker、tomcat、elasticsearch、nginx、keepalived-opt、nacos-cluster 等） |
| 计算/采样 | 每目标一次；ActiveState=active 为正常 |
| 单位 | 枚举（active/inactive/failed/unknown/not-found） |
| 来源锚点 | 巡检手册 P0 服务行（Nginx T5R1/T5R4、Redis T5R1、Rabbitmq T5R1、Mysql T5R1、Nacos T5R1）+ 部署规范 systemd 章节（Mysql T11、Redis T13/T24、Rocketmq T18/T19、Tomcat T15、ES T7） |
| 阈值层 | 文档基线 + 外部配置（unit 名）覆盖；无配置 → UNKNOWN |
| 适用条件 | 以 systemd 管理且 unit 名已知的产品；unit 命名冲突见 docx-source-conflicts.md C8 |
| 权限/能力失败 | 无权限读取 → UNKNOWN |
| 超时 | 10s |
| 证据 | 命令输出（ActiveState、unit 名） |
| 脱敏 | 无敏感数据；unit 名属配置边界 |
| 文档基线 | active → OK；非 active/进程不存在 → CRIT（故障）；反复重启 → WARN |

### 5.3 local.port.listening — 端口监听

| 字段 | 内容 |
| --- | --- |
| 数据源 | `ss -tlnp` 按端口过滤（如 `ss -tlnp \| grep -E ":9200|:9300"`），并核对监听进程与产品进程一致 |
| 计算/采样 | 每目标一次；端口与监听进程均匹配为正常 |
| 单位 | 枚举（listening/not-listening）+ 端口列表 |
| 来源锚点 | 巡检手册 P0 端口行（ES T5R8、Kafka T5R10、Nacos T5R2、Redis T5R3、Rabbitmq T5R3、Rocketmq T5R4、Tomcat T5R2、Nginx T5R3）+ 环境信息端口表 |
| 阈值层 | 文档基线 + 外部配置（端口+模式）覆盖；无配置 → UNKNOWN |
| 适用条件 | 端口按产品与部署模式（Redis 单机 6379/哨兵 16379+26379/Cluster 7000+17000；Kafka 9093 安全配置、9092 遗留） |
| 权限/能力失败 | `ss` 权限不足或不可用 → UNKNOWN |
| 超时 | 10s |
| 证据 | `ss` 输出（监听地址、进程）已脱敏 |
| 脱敏 | 监听 IP 脱敏为 `<IP>` |
| 文档基线 | 端口监听且进程匹配 → OK；不监听 → CRIT（故障）；模式外端口仍开放（如 9092）→ WARN 需确认 |

### 5.4 local.cpu.utilization — CPU 使用率

| 字段 | 内容 |
| --- | --- |
| 数据源 | `top -bn1`（CPU 行）+ `ps -eo pid,comm,%cpu,%mem --sort=-%cpu`（Top 进程） |
| 计算/采样 | 两次采样取趋势；`%cpu` 为瞬时/均值参考，结合 load 与业务证据判读 |
| 单位 | % |
| 来源锚点 | 9 份巡检手册 P0 CPU 行（ES T5R3、Kafka T5R7、Mysql T5R7、Nacos T5R7、Rabbitmq T5R8、Redis T5R9、Rocketmq T5R8、Nginx T5R9、Tomcat T5R6） |
| 阈值层 | 文档基线（linux-common-p0-v1）+ 外部配置覆盖；Nginx/Tomcat 阈值差异见冲突 C2 |
| 适用条件 | 全部产品；Nginx 手册仅定义 80% 关注层，Tomcat 手册为相对判据（见 C2） |
| 权限/能力失败 | 无法采样 → UNKNOWN |
| 超时 | 10s |
| 证据 | top/ps 输出摘要（已脱敏进程行） |
| 脱敏 | 进程命令行、PID 按配置边界 |
| 文档基线 | 长期 <70% 且短时波动 <80% → OK；持续 >80% → WARN（关注）；>90% 且伴随业务证据（查询/写入延迟、生产/消费延迟、客户端超时、复制延迟）→ CRIT（告警）；load 持续高于核数 → 需排查（归入 load 指标证据） |

### 5.5 local.cpu.load_1m — 系统负载

| 字段 | 内容 |
| --- | --- |
| 数据源 | `/proc/loadavg` 或 `uptime`（load_1m/5m/15m）+ CPU 核数（`nproc` 或 `/proc/cpuinfo`） |
| 计算/采样 | 同时采集 load_1m、load_5m、load_15m；每个窗口均与 CPU 核数比较。"不持续高于核数"需至少两次采样（间隔 ≥60s）确认持续性 |
| 单位 | 1/5/15 分钟系统负载数值；正常窗口的 stdout 描述为“1 分钟系统负载：值（1分钟，CPU核数=N，负载/核数=实际比值，阈值<=1.00，正常）” |
| 来源锚点 | 9 份巡检手册 P0 CPU 行正常标准"load_1m 不持续高于 CPU 核数"（ES T5R3、Kafka T5R7、Nacos T5R7、Rabbitmq T5R8、Redis T5R9、Rocketmq T5R8） |
| 阈值层 | 文档基线：每个负载窗口 ≤ 核数 → OK；> 核数且持续：文档仅要求"排查/关注"，**未定义告警等级**（缺失边界）→ 默认 UNKNOWN，外部配置可覆盖；metric 级兼容状态仍以 load_1m 为准 |
| 适用条件 | 全部产品；核数无法获取 → 判据不可用 → UNKNOWN |
| 权限/能力失败 | /proc 不可读 → UNKNOWN |
| 超时 | 10s |
| 证据 | load_1m/load_5m/load_15m 原始值、CPU 核数及每个窗口的 status/judgement |
| 脱敏 | 无 |
| 文档基线 | 每个负载窗口 ≤ 核数 → OK，并显示“窗口系统负载：值（窗口，CPU核数=N，负载/核数=实际比值，阈值<=1.00，正常）”；持续 > 核数 → 等级缺失 → UNKNOWN（建议外部配置：如持续 > 核数 → WARN）。metric 级兼容状态仍以 load_1m 为准。 |

### 5.6 local.memory.available_percent — 可用内存百分比

| 字段 | 内容 |
| --- | --- |
| 数据源 | `free -h`/`free -m`（available 字段） |
| 计算/采样 | available/总内存 × 100，取整 |
| 单位 | % |
| 来源锚点 | 9 份巡检手册 P0 内存行（ES T5R4、Kafka T5R8、Mysql T5R8、Nacos T5R8、Rabbitmq T5R9、Rocketmq T5R9、Nginx T5R9、Tomcat T5R7、Redis T5R7） |
| 阈值层 | 文档基线 + 外部配置覆盖 |
| 适用条件 | 全部产品 |
| 权限/能力失败 | free 不可用 → UNKNOWN |
| 超时 | 10s |
| 证据 | free 输出（available/total） |
| 脱敏 | 无 |
| 文档基线 | ≥20% → OK（ES：不低于 20%；其余：>20%，措辞差异见冲突 C4，数值一致）；<10% → CRIT（告警）；10%–20% 区间**文档未定义** → 默认 UNKNOWN，外部配置可覆盖 |

### 5.7 local.swap.used_percent — Swap 使用率

| 字段 | 内容 |
| --- | --- |
| 数据源 | `free -h` Swap 行（used/total）或 `/proc/meminfo` SwapTotal/SwapFree |
| 计算/采样 | used/total × 100；total=0 视为未配置 Swap |
| 单位 | % |
| 来源锚点 | 9 份巡检手册 P0 内存行（ES T5R4、Kafka T5R8、Mysql T5R8、Nacos T5R8、Rabbitmq T5R9、Rocketmq T5R9、Tomcat T5R7） |
| 阈值层 | 文档基线 + 外部配置覆盖；判据冲突见冲突 C3 |
| 适用条件 | 全部产品；swap=0 为部署基线（ES/部署规范） |
| 权限/能力失败 | 无法读取 → UNKNOWN |
| 超时 | 10s |
| 证据 | free/proc 输出 |
| 脱敏 | 无 |
| 文档基线 | used=0（或未配置）→ OK（全部手册一致：Swap 为 0 或未使用）；used>0 → **文档冲突未解决**（5 份手册=告警/故障、ES=需确认部署基线、Tomcat=持续使用为风险、Nginx/Redis 未定义）→ 默认 UNKNOWN，外部配置可覆盖 |

### 5.8 local.filesystem.used_percent — 磁盘使用率

| 字段 | 内容 |
| --- | --- |
| 数据源 | `df -hT`（采集全部文件系统；不再限定 `/` 或 profile 路径） |
| 计算/采样 | used/total × 100；所有挂载点进入 `evidence.details`，每条明细保存挂载点级 `status`；`normalized_value` 保留全部挂载点最大值用于指标整体阈值判定 |
| 单位 | % |
| 来源锚点 | 9 份巡检手册 P0 磁盘行（ES T5R5、Kafka T5R9、Mysql T5R9、Nacos T5R9、Rabbitmq T5R10、Redis T5R10、Rocketmq T5R10、Nginx T5R10、Tomcat T5R8） |
| 阈值层 | 文档基线（75/85/95 分层）+ 外部配置覆盖；Nginx/Tomcat 建议线 80% 差异见冲突 C1 |
| 适用条件 | 全部产品；路径属配置边界（部署规范目录） |
| 权限/能力失败 | 目录不可读 → UNKNOWN |
| 超时 | 10s |
| 证据 | df 输出（文件系统、使用率） |
| 脱敏 | 挂载路径含主机/卷信息时按配置边界 |
| 文档基线 | <75% → OK（Nginx/Tomcat 手册为 <80%，冲突 C1，外部配置可覆盖）；75–85% → WARN（关注）；>85% → CRIT（告警）；>95% → CRIT（故障风险：写入失败/flood stage，ES 手册另有 >90% 严重告警层，见冲突 C6，状态同为 CRIT） |

### 5.9 local.filesystem.inode_used_percent — inode 使用率

| 字段 | 内容 |
| --- | --- |
| 数据源 | `df -i`（采集全部文件系统；不再限定 `/` 或 profile 路径） |
| 计算/采样 | used/total × 100；所有挂载点进入 `evidence.details`，每条明细保存挂载点级 `status`；`normalized_value` 保留全部挂载点最大值用于指标整体阈值判定 |
| 单位 | % |
| 来源锚点 | 9 份巡检手册 P0 磁盘行（ES T5R5、Kafka T5R9、Mysql T5R9、Nacos T5R9、Rabbitmq T5R10、Redis T5R10、Rocketmq T5R10、Nginx T5R10、Tomcat T5R8） |
| 阈值层 | 文档基线 + 外部配置覆盖；≥80% 边界缺失见冲突 C5 |
| 适用条件 | 全部产品 |
| 权限/能力失败 | df 不可用 → UNKNOWN |
| 超时 | 10s |
| 证据 | df -i 输出 |
| 脱敏 | 无 |
| 文档基线 | <80% → OK（全部手册一致）；≥80% → 文档仅描述"接近耗尽"未给数值边界 → 默认 UNKNOWN，外部配置可覆盖 |

### 5.10 local.logs.key_evidence — 关键日志证据

| 字段 | 内容 |
| --- | --- |
| 数据源 | 按产品 profile 的日志路径与关键词（如 ES：`tail -300 /opt/elasticsearch/logs/*.log \| egrep -i 'ERROR|WARN|exception|master not discovered|flood stage'`；Kafka：`grep -R -iE 'ERROR|FATAL|OutOfMemory|...' /opt/kafka/logs`） |
| 计算/采样 | 最近 N 行/天内匹配不可解释错误关键词；计数与原文摘录 |
| 单位 | 匹配行数 + 关键词分布 |
| 来源锚点 | 9 份巡检手册 P0 关键日志行（ES T5R11、Kafka T5R11、Mysql T5R11、Nacos T5R10、Rabbitmq T5R11、Redis T5R11、Rocketmq T5R11、Nginx T5R11、Tomcat T5R5） |
| 阈值层 | 文档基线：无新增不可解释 ERROR/FATAL → OK；具体关键词集合为产品 profile 配置 |
| 适用条件 | 全部产品；日志路径属配置边界 |
| 权限/能力失败 | 日志不可读 → UNKNOWN（不作为 OK 处理） |
| 超时 | 15s（大日志文件按 tail/grep 限制） |
| 证据 | 关键词、命中行数、最近命中行摘要（原文保留在原始输出，脱敏后入库） |
| 脱敏 | 日志行中 IP、凭据、业务标识脱敏 |
| 文档基线 | 无新增不可解释 ERROR/FATAL、WARN 均可解释 → OK；出现 OOM/磁盘满/连接耗尽/主从异常/认证失败等（按产品关键词）→ WARN 或 CRIT（按产品手册判定，冲突未解决的取 UNKNOWN，见冲突 C10） |

## 6. 阈值汇总表（linux-common-p0-v1 文档基线）

| metric_id | OK | WARN | CRIT | 无规则/冲突 → UNKNOWN 边界 |
| --- | --- | --- | --- | --- |
| local.process.present | 进程存在 | 反复重启 | 进程缺失（故障） | 无 profile 配置 |
| local.service.active | active | 反复重启 | 非 active（故障） | unit 名无配置/冲突 C8 |
| local.port.listening | 监听且进程匹配 | 模式外端口开放 | 不监听（故障） | 端口/模式无配置 |
| local.cpu.utilization | 长期<70% 且波动<80% | 持续>80% | >90% 且伴随业务证据 | Nginx/Tomcat 差异 C2 |
| local.cpu.load_1m | ≤核数 | （文档未定义） | （文档未定义） | 持续>核数 → 缺失 → UNKNOWN |
| local.memory.available_percent | ≥20% | （10–20% 未定义 → UNKNOWN） | <10% | 10–20% 区间 C4 |
| local.swap.used_percent | =0 或未配置 | （文档未定义） | （文档未定义） | >0 → 冲突 C3 → UNKNOWN |
| local.filesystem.used_percent | <75%（Nginx/Tomcat <80%） | 75–85% | >85%（>95% 故障风险） | 建议线冲突 C1（外部配置覆盖） |
| local.filesystem.inode_used_percent | <80% | （文档未定义） | （文档未定义） | ≥80% → 缺失 C5 → UNKNOWN |
| local.logs.key_evidence | 无可解释错误 | 隐患级关键词（按产品） | 故障级关键词（按产品） | 日志不可读/关键词集无配置 |

## 7. 冲突与缺失索引

本文件各指标引用的文档冲突（C1–C13）与缺失边界详见 docs/reviews/docx-source-conflicts.md；任何"默认 UNKNOWN"的边界均可由外部配置覆盖并在 `provenance` 中记录配置来源。禁止在无文档锚点或未批准配置的情况下修改本表阈值。
