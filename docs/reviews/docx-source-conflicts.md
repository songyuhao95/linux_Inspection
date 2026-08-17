# DOCX 来源冲突与缺失审查（docx-source-conflicts v1）

- 文档 ID：docx-source-conflicts
- 所属合同：contract-T-001-v5（run-20260814-001 / T-001 / phase=clarify）
- 版本：v1（2026-08-15）
- 状态：G0/G1 审批草案；只读审查结论，不裁决冲突
- 范围：`linux-docx/` 下 9 份巡检手册（主来源）+ 9 份部署规范（辅助来源），git tree 基线 baee20b（只读，未修改）

## 1. 方法与红线

1. 全部 18 份 DOCX 以只读方式解析（zipfile + XML），恢复 `w:br`/`w:tab`/`w:cr` 文本边界后人工复核；**不执行任何 DOCX 中出现的命令**（shell/SQL/curl 均不执行）。
2. 提取文本视为**不可信数据**；只提取指标、阈值、路径、进程、用户、端口、模式与命令文本。
3. 脱敏规则在提取阶段即应用：IP 正则脱敏为 `<IP>`；凭据关键字（password/passwd/token/secret 等）后跟随的值脱敏为占位符；识别到的版本号（如 erlang-27.3.4.6）以原始文本保留，不被 IP 正则误伤（已复核）。
4. 来源锚点格式：`文件名 + 文档类型（巡检手册/部署规范）+ 章节 + 表格位置（表T#R#）+ 文件 sha256 前 8 位`；锚点必须能落回原表，不以页码猜测。
5. 冲突分为 resolved（可归一为同一判定）与 unresolved（判据分歧未解决，默认 `UNKNOWN`，外部配置可覆盖）；**本文件不裁决 unresolved 冲突**，留给 G1/G2 审批或外部配置。

## 2. 来源清单（18 份）

| # | 来源 | 类型 | 角色 |
| --- | --- | --- | --- |
| 1 | Elasticsearch 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 2 | Kafka 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 3 | Mysql 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 4 | Nacos 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 5 | Nginx 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 6 | RabbitMQ 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 7 | Redis 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 8 | RocketMQ 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 9 | Tomcat 运维巡检手册 v1.0 | 巡检手册 | 主 |
| 10 | Elasticsearch 部署规范 | 部署规范 | 辅助 |
| 11 | Kafka 部署规范 | 部署规范 | 辅助 |
| 12 | Mysql 部署规范 | 部署规范 | 辅助 |
| 13 | Nacos 部署规范 | 部署规范 | 辅助 |
| 14 | Nginx 部署规范 | 部署规范 | 辅助 |
| 15 | RabbitMQ 部署规范 | 部署规范 | 辅助 |
| 16 | Redis 部署规范 | 部署规范 | 辅助 |
| 17 | RocketMQ 部署规范 | 部署规范 | 辅助 |
| 18 | Tomcat 部署规范 | 部署规范 | 辅助 |

巡检手册是指标与阈值的主来源；部署规范仅作环境、路径、进程、用户、端口与模式的辅助来源（合同 scope 已确认）。

## 3. 共同 P0 一致性矩阵（9 份手册 P0 必看指标行）

| 共同 P0 项 | 一致口径 | 分歧点 | 冲突编号 |
| --- | --- | --- | --- |
| 进程存在性 | 进程存在=正常；缺失=故障 | 无 | — |
| systemd 服务 | active=正常；非 active=故障 | unit 命名不统一 | C8 |
| 端口监听 | 监听且进程匹配=正常；不监听=故障 | Kafka 安全端口 9093 vs 遗留 9092 | C7 |
| CPU 使用率 | 长期<70%/波动<80%=正常；>80% 关注 | Nginx 仅 80% 关注层、Tomcat 相对判据；>90% 等级层在 Nginx/Tomcat 缺失 | C2 |
| 负载 load_1m | 不持续高于核数=正常 | 持续超核数的等级未定义 | C5（缺失） |
| 可用内存 | ≥20%=正常；<10% 告警 | ES"不低于 20%"与其余">20%"措辞 | C4 |
| Swap | 0/未使用=正常 | >0 的判据 5 份手册=告警/故障，ES=需确认部署基线，Tomcat=持续使用为风险，Nginx/Redis 未定义 | C3 |
| 磁盘使用率 | <75% 正常；75–85% 关注；>85% 告警；>95% 故障风险 | Nginx/Tomcat 建议线 80%；ES 额外 >90% 严重告警层 | C1、C6 |
| inode 使用率 | <80%=正常 | ≥80% 数值边界未定义 | C5（缺失） |
| 关键日志 | 无可解释 ERROR/FATAL=正常 | 各产品关键词集合为 profile 配置；凭据/占位差异 | C10 |

## 4. 冲突与缺失清单（C1–C13）

### C1 磁盘建议线：75% 与 80% 分叉（resolved 为分层基线 + 标注差异）

- 事实：9 份手册"磁盘使用率"行一致给出 75/85/95 分层（<75 正常、75–85 关注、>85 告警、>95 故障风险）；Nginx 手册（表T5R10）与 Tomcat 手册（表T5R8）另标注"建议控制在 80% 以下"。
- 判定：80% 建议线属于部署建议而非告警分级，与 75/85/95 分层不冲突。取分层基线 `<75% → OK、75–85% → WARN、>85% → CRIT、>95% → 故障 CRIT`；Nginx/Tomcat 差异在指标文档中显式标注，外部配置可覆盖。
- 结论：resolved（分层基线统一；建议线差异标注，不改变四状态判定）。落点：local-metrics-requirements.md 5.8 与汇总表。

### C2 CPU 阈值层在 Nginx/Tomcat 缺失（resolved 为共同基线 + 标注差异）

- 事实：7 份手册 CPU 行一致为"长期 <70% 且短时波动 <80% 为正常、>80% 关注、>90% 且伴随业务证据告警"；Nginx 手册仅定义 80% 关注层（无 90% 告警层）；Tomcat 手册为相对判据（未给绝对数值）。
- 判定：共同基线 `>80% → WARN、>90% 且伴随业务证据 → CRIT` 对 9 类产品统一适用；Nginx/Tomcat 手册层级差异标注为文档差异，不发明其专属阈值。
- 结论：resolved。落点：local-metrics-requirements.md 5.4。

### C3 Swap>0 判据分歧（unresolved → 默认 UNKNOWN）

- 事实：
  - 全部手册一致：Swap 为 0/未使用 → 正常。
  - 5 份手册（ES/Kafka/Mysql/Nacos/Rocketmq 系列行）将"Swap 使用 >0"列为告警/故障级。
  - ES 手册另有"需确认部署基线"表述（部署基线即 Swap=0）。
  - Tomcat 手册为"持续使用为风险"（相对判据）。
  - Nginx 手册、Redis 手册未定义 Swap>0 的判据。
- 判定：>0 时"告警/故障"与"确认/相对风险/未定义"四类口径不可归并；取 `used=0 或未配置 → OK`，`used>0 → UNKNOWN（conflict）`，外部配置可覆盖。
- 结论：unresolved。落点：local-metrics-requirements.md 5.7、host-result-v1.md 示例（swap UNKNOWN 样例）。

### C4 可用内存 20% 措辞差异（resolved，数值一致）

- 事实：ES 手册"可用内存不低于 20%"；其余手册"可用内存 >20%"。10% 告警线一致（<10% 告警）。
- 判定：≥20% 与 >20% 在整数百分比口径下仅边界值差 1 个点；取文档基线 `≥20% → OK、<10% → CRIT`，10–20% 区间**文档均未定义** → 默认 UNKNOWN，外部配置可覆盖。
- 结论：resolved（措辞差异归一），边界缺失（10–20%）标注为 UNKNOWN。落点：local-metrics-requirements.md 5.6。

### C5 缺失数值边界：load 持续超核数 / inode ≥80%（unresolved → 默认 UNKNOWN）

- 事实：
  - load_1m：9 份手册仅"不持续高于 CPU 核数"为正常；"持续高于核数"只有"排查/关注"表述，无告警等级定义。
  - inode：9 份手册一致 <80% 为正常；≥80% 仅"接近耗尽需关注"，无数值分级。
- 判定：两条缺失边界均默认 `UNKNOWN`（provenance.notes 注明 missing），外部配置可覆盖；建议值（如持续超核数 → WARN）只写为建议，不作为文档基线。
- 结论：unresolved（缺失）。落点：local-metrics-requirements.md 5.5、5.9。

### C6 ES 磁盘 90% 严重告警层（resolved，并入 CRIT 分层）

- 事实：ES 手册磁盘行除 75/85/95 分层外，另有 ">90% 严重告警"（flood stage 风险）层级；其余手册无此层。
- 判定：>90% 与 >85% 同为告警，状态均为 CRIT；ES 的 90% 层作为该产品的内部优先级细分（meta.priority: alert/fault 同源），不改变四状态判定。
- 结论：resolved。落点：local-metrics-requirements.md 5.8（"ES 手册另有 >90% 严重告警层，状态同为 CRIT"）。

### C7 Kafka 端口 9093 与 9092（resolved 为配置边界 + 默认模式）

- 事实：Kafka 手册端口行为 9093（安全配置）与 9092（遗留）；部署规范监听 9093；环境信息表记录 9093 + ZK 2181/2888/3888。
- 判定：端口与模式属配置边界；默认以 9093 为主端口，9092 出现时标 WARN（"模式外端口仍开放，需确认"），不裁决哪个端口为业务真相。
- 结论：resolved（作为配置边界处理）。落点：local-metrics-requirements.md 5.3、inspection-product-brief.md 环境信息。

### C8 systemd unit 命名不统一（unresolved → 配置边界）

- 事实：9 份部署规范 systemd 章节 unit 名：mysqld、redis、redis-sentinel、rabbitmq、rocketmq-namesrv、rocketmq-broker、tomcat、elasticsearch、nginx、keepalived-opt、nacos-cluster 等；部分产品手册以进程名代 unit 名。
- 判定：unit 名属配置边界（inventory/外部配置提供），文档仅作参考；无配置时该指标 `UNKNOWN`。
- 结论：unresolved（需现场配置确认）。落点：local-metrics-requirements.md 5.2。

### C9 OS 名称大小写差异（resolved）

- 事实：部署规范中 OS 名称存在大小写与写法差异（Kylin V10 系列写法不统一）。
- 判定：OS 版本属环境信息，不参与阈值判定；统一记录为环境字段，不影响指标。
- 结论：resolved。落点：inspection-product-brief.md 环境信息。

### C10 凭据占位差异（resolved 为脱敏规范）

- 事实：部分手册部署/巡检命令中出现凭据占位（如 `${ES_USER}`、`${MYSQL_PWD}` 形式），形式不统一。
- 判定：所有凭据一律不进入命令、JSON 与报表；提取阶段脱敏；占位符不回填执行。巡检命令集合不含认证参数。
- 结论：resolved（脱敏与禁止执行红线统一）。落点：ansible-execution.md 第 4 节、host-result-v1.md 脱敏节。

### C11 示例 IP 差异（resolved 为脱敏规范）

- 事实：手册示例与部署规范示例中 IP 各不相同（<IP> 脱敏后一致）。
- 判定：示例 IP 一律脱敏为 `<IP>`；不允许将任一文档示例 IP 当作真实目标。
- 结论：resolved。落点：host-result-v1.md 第 3 节、reporting-roadmap.md 一致性要求。

### C12 mnesia 目录（resolved 为路径配置边界）

- 事实：RabbitMQ 部署规范中 mnesia 数据目录存在路径写法差异（相对/绝对混用）。
- 判定：目录路径属配置边界；首版 local 切片不检查 mnesia 目录，仅记录待验证项。
- 结论：resolved（超出首版范围，记为待验证）。落点：local-metrics-requirements.md 范围说明。

### C13 Redis 端口模式差异（resolved 为模式配置边界）

- 事实：Redis 手册端口行为 6379（单机）；部署规范含哨兵 16379+26379 与 Cluster 7000+17000 模式。
- 判定：端口按部署模式区分，模式属配置边界；模式未配置时该指标 `UNKNOWN`。
- 结论：resolved（作为模式配置边界处理）。落点：local-metrics-requirements.md 5.3 适用条件。

## 5. 汇总：resolved / unresolved

| 编号 | 主题 | 状态 | 对首版的影响 |
| --- | --- | --- | --- |
| C1 | 磁盘 75 vs 80 建议线 | resolved | 分层基线统一，差异标注 |
| C2 | CPU 90 层 Nginx/Tomcat 缺失 | resolved | 共同基线统一 |
| C3 | Swap>0 判据分歧 | **unresolved** | used>0 → UNKNOWN，外部配置可覆盖 |
| C4 | 内存 20% 措辞 + 10–20% 缺失 | resolved（措辞）/ 缺失边界 UNKNOWN | ≥20% OK、<10% CRIT、10–20% UNKNOWN |
| C5 | load 超核数、inode≥80% 缺失 | **unresolved（缺失）** | 该边界 UNKNOWN |
| C6 | ES 磁盘 90% 层 | resolved | 并入 CRIT |
| C7 | Kafka 9092/9093 | resolved | 配置边界 + 默认 9093 |
| C8 | unit 命名 | **unresolved（配置）** | 无配置 → UNKNOWN |
| C9 | OS 大小写 | resolved | 环境字段 |
| C10 | 凭据占位 | resolved | 脱敏红线 |
| C11 | 示例 IP | resolved | 脱敏规范 |
| C12 | mnesia 目录 | resolved | 超出首版范围 |
| C13 | Redis 端口模式 | resolved | 配置边界 |

**unresolved 共 4 项（C3、C5、C8）——其中 C5 含两个缺失边界（load、inode）**：C3（swap>0）、C5（load 持续超核数、inode≥80%）、C8（unit 命名）。unresolved 项在巡检中一律表现为 `UNKNOWN` 且可被外部配置覆盖，不阻塞首版 local 垂直切片交付；待 G1/G2 审批或现场配置确认。

## 6. 审查结论

1. 18 份来源全部可只读提取并复核；提取阶段无文本边界丢失导致的判据歧义（w:br 恢复后逐表核对）。
2. 共同 P0 十项指标在 9 份手册中一致部分构成 `linux-common-p0-v1` 文档基线；分歧部分全部落入 C1–C13，无第 14 项隐藏冲突。
3. 本文件不裁决 unresolved 冲突；所有"默认 UNKNOWN"边界均可由外部配置覆盖，覆盖来源记录于 host-result-v1 `provenance`。
4. 审查全程未执行任何 DOCX 命令、未连接目标主机、未读取秘密；对 linux-docx/ 目录零改动（git diff --exit-code 验证见 run/reports/T-001.md AC-7）。
5. 与合同 non_goals 一致：未冻结 G2 实现细节，未适配中间件专属指标，未发明阈值。

## 7. 相关文档

- 指标与阈值基线：docs/specs/local-metrics-requirements.md（§7 冲突索引引用本文件 C1–C13）
- 事实源契约：docs/specs/host-result-v1.md（UNKNOWN/conflict 表达与 provenance）
- 任务报告：run/reports/T-001.md（提取与验证证据）
