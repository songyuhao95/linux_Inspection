"""10 个共同 P0 指标注册表（linux-common-p0-v1，T-101）。

每条指标定义锚定 docs/specs/local-metrics-requirements.md §5（字段与来源锚点）
与 docs/specs/technical-design.md §5.2（采集命令、超时、解析器约定）。
本模块只提供**定义数据**，不执行任何采集命令、不做阈值判定
（阈值判定属 T-102 基线文件/T-104 normalize 范围；规则 ID 仅作引用）。

字段契约（tests/test_metrics.py 机械校验，增删需同步合同）：
  metric_id         版本化标识（如 local.cpu.utilization）
  name              中文名称（--list-metrics 展示）
  command           采集命令（MR §5 数据源列只读转译，含 <profile> 配置占位）
  timeout_sec       采集超时上限（MR §5 超时列：10s，日志类 15s）
  parser            解析器名（TD §5.2；normalize.py T-104 按名注册实现）
  unit              单位（MR §5 单位列）
  source_anchor     来源锚点（MR §2 格式：文件名+文档类型+章节+表T#R#+sha256[:8]）
  threshold_layer   阈值层（MR §3：文档基线/外部配置覆盖/无规则冲突→UNKNOWN）
  threshold_rule_ids 阈值规则 ID 引用（MR §6 汇总行 + 冲突/缺失编号 C1-C13）
  conflicts         冲突/缺失备注（docs/reviews/docx-source-conflicts.md 编号）
  doc_baseline      文档基线判定摘要（MR §5 文档基线列）
  unknown_conditions UNKNOWN 条件（MR §5 权限/能力失败与缺失边界列）
"""

# 来源文件指纹（linux-docx/，基线 baee20b 只读）：文件 sha256 前 8 位
_MANUAL_SHA = (
    "巡检手册 sha256[:8]: ES=bb8ff97e, Kafka=0772f967, Mysql=67ae309b, "
    "Nacos=43cad170, Nginx=72b0834d, Rabbitmq=a6e0861f, Redis=e5cf1a4d, "
    "Rocketmq=9d70e22c, Tomcat=49aa5707"
)
_DEPLOY_SHA = (
    "部署规范 sha256[:8]: ES=246a0387, Kafka=7021c214, Mysql=e0571b68, "
    "Nacos=d3233b50, Nginx=06707079, Rabbitmq=5b5b42a0, Redis=c4b82daf, "
    "Rocketmq=8cbcd254, Tomcat=c0046da0"
)

# 阈值规则 ID 前缀：文档基线版本标识（MR §6 汇总表，T-102 转写基线 YAML）
_RULE_PREFIX = "linux-common-p0-v1"

VERSION = _RULE_PREFIX

METRICS = [
    {
        "metric_id": "local.process.present",
        "name": "进程存在性",
        "command": "pgrep -fa '<profile 进程模式>' || ps -ef | grep '[p]attern'"
                   "（pattern 来自产品 profile 配置）",
        "timeout_sec": 10,
        "parser": "parse_process_present",
        "unit": "布尔（present/absent）+ 匹配行数",
        "source_anchor": (
            "9 份运维巡检手册 §三(二)P0必看指标-服务/进程行"
            "（如 Kafka 手册 T5R2、Tomcat 手册 T5R1、Redis 手册 T5R1；"
            "示例命令 pgrep -fa 'kafka.Kafka'、ps -ef | grep '[o]rg.apache.catalina.startup.Bootstrap'）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线（进程存在=正常）+ 外部配置（进程模式）覆盖；无 profile → UNKNOWN",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.process.present"],
        "conflicts": [],
        "doc_baseline": "进程存在 → OK；进程不存在 → CRIT（故障）；服务反复重启 → WARN",
        "unknown_conditions": "无 profile 配置、无权限或 pgrep 不可用 → UNKNOWN，继续其余指标",
    },
    {
        "metric_id": "local.service.active",
        "name": "systemd 服务状态",
        "command": "systemctl is-active <unit>; systemctl show -p ActiveState,SubState <unit>"
                   "（unit 名来自产品 profile/部署规范）",
        "timeout_sec": 10,
        "parser": "parse_service_active",
        "unit": "枚举（active/inactive/failed/unknown/not-found）",
        "source_anchor": (
            "巡检手册 P0 服务行（Nginx T5R1/T5R4、Redis T5R1、Rabbitmq T5R1、"
            "Mysql T5R1、Nacos T5R1）+ 部署规范 systemd 章节"
            "（Mysql T11、Redis T13/T24、Rocketmq T18/T19、Tomcat T15、ES T7）；"
            + _MANUAL_SHA + "；" + _DEPLOY_SHA
        ),
        "threshold_layer": "文档基线 + 外部配置（unit 名）覆盖；无配置 → UNKNOWN",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.service.active"],
        "conflicts": ["C8（unit 命名冲突，配置边界）"],
        "doc_baseline": "active → OK；非 active/进程不存在 → CRIT（故障）；反复重启 → WARN",
        "unknown_conditions": "unit 无配置/冲突（C8）、无权限读取 → UNKNOWN",
    },
    {
        "metric_id": "local.port.listening",
        "name": "端口监听",
        "command": "ss -tlnp | grep -E ':<profile 端口>'（核对监听进程与产品进程一致）",
        "timeout_sec": 10,
        "parser": "parse_port_listening",
        "unit": "枚举（listening/not-listening）+ 端口列表",
        "source_anchor": (
            "巡检手册 P0 端口行（ES T5R8、Kafka T5R10、Nacos T5R2、Redis T5R3、"
            "Rabbitmq T5R3、Rocketmq T5R4、Tomcat T5R2、Nginx T5R3）+ 环境信息端口表；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线 + 外部配置（端口+模式）覆盖；无配置 → UNKNOWN",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.port.listening"],
        "conflicts": ["C7（模式外端口仍开放如 Kafka 9092 → WARN 需确认）", "C13（端口/模式无配置）"],
        "doc_baseline": "端口监听且进程匹配 → OK；不监听 → CRIT（故障）；模式外端口开放 → WARN",
        "unknown_conditions": "端口/模式无配置（C13）、ss 权限不足或不可用 → UNKNOWN",
    },
    {
        "metric_id": "local.cpu.utilization",
        "name": "CPU 使用率",
        "command": "top -bn2 -d 1 | grep 'Cpu(s)' | tail -1；ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -10",
        "timeout_sec": 10,
        "parser": "parse_cpu_utilization",
        "unit": "%",
        "source_anchor": (
            "9 份巡检手册 P0 CPU 行（ES T5R3、Kafka T5R7、Mysql T5R7、Nacos T5R7、"
            "Rabbitmq T5R8、Redis T5R9、Rocketmq T5R8、Nginx T5R9、Tomcat T5R6）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线（linux-common-p0-v1）+ 外部配置覆盖",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.cpu.utilization"],
        "conflicts": ["C2（Nginx 仅 80% 关注层、Tomcat 相对判据，阈值差异）"],
        "doc_baseline": "长期 <70% 且短时波动 <80% → OK；持续 >80% → WARN（关注）；"
                        ">90% 且伴随业务证据 → CRIT（告警）",
        "unknown_conditions": "无法采样 → UNKNOWN；>90% 无业务证据采集能力 → 保持 WARN 并在 provenance 注明",
    },
    {
        "metric_id": "local.cpu.load_1m",
        "name": "系统负载",
        "command": "cat /proc/loadavg；nproc（或 /proc/cpuinfo 核数）",
        "timeout_sec": 10,
        "parser": "parse_cpu_load_1m",
        "unit": "数值（相对核数，无量纲）",
        "source_anchor": (
            "9 份巡检手册 P0 CPU 行正常标准“load_1m 不持续高于 CPU 核数”"
            "（ES T5R3、Kafka T5R7、Nacos T5R7、Rabbitmq T5R8、Redis T5R9、Rocketmq T5R8）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线 + 缺失边界 → 默认 UNKNOWN，外部配置可覆盖",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.cpu.load_1m"],
        "conflicts": ["C5（持续>核数的告警等级缺失）"],
        "doc_baseline": "load_1m ≤ 核数 → OK；持续 > 核数 → 等级缺失 → UNKNOWN"
                        "（建议外部配置：如持续 > 核数 → WARN）",
        "unknown_conditions": "核数无法获取、/proc 不可读、持续性确认采样不足 → UNKNOWN",
    },
    {
        "metric_id": "local.memory.available_percent",
        "name": "可用内存百分比",
        "command": "free -m（available 字段；available/总内存 × 100 取整）",
        "timeout_sec": 10,
        "parser": "parse_memory_available_percent",
        "unit": "%",
        "source_anchor": (
            "9 份巡检手册 P0 内存行（ES T5R4、Kafka T5R8、Mysql T5R8、Nacos T5R8、"
            "Rabbitmq T5R9、Rocketmq T5R9、Nginx T5R9、Tomcat T5R7、Redis T5R7）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线 + 外部配置覆盖",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.memory.available_percent"],
        "conflicts": ["C4（10%–20% 区间文档未定义，措辞差异数值一致）"],
        "doc_baseline": "≥20% → OK；<10% → CRIT（告警）；10%–20% → 缺失 → UNKNOWN"
                        "（外部配置可覆盖）",
        "unknown_conditions": "free 不可用、10%–20% 区间无外部配置 → UNKNOWN",
    },
    {
        "metric_id": "local.swap.used_percent",
        "name": "Swap 使用率",
        "command": "free -m Swap 行（used/total）或 /proc/meminfo SwapTotal/SwapFree"
                   "（used/total × 100；total=0 视为未配置）",
        "timeout_sec": 10,
        "parser": "parse_swap_used_percent",
        "unit": "%",
        "source_anchor": (
            "9 份巡检手册 P0 内存行（ES T5R4、Kafka T5R8、Mysql T5R8、Nacos T5R8、"
            "Rabbitmq T5R9、Rocketmq T5R9、Tomcat T5R7）；swap=0 为部署基线（ES/部署规范）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线 + 外部配置覆盖；used>0 判据冲突 → 默认 UNKNOWN",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.swap.used_percent"],
        "conflicts": ["C3（used>0：5 份手册=告警/故障、ES=需确认部署基线、"
                      "Tomcat=持续使用为风险、Nginx/Redis 未定义，冲突未解决）"],
        "doc_baseline": "used=0（或未配置 swap）→ OK（全部手册一致）；used>0 → UNKNOWN"
                        "（冲突 C3，外部配置可覆盖）",
        "unknown_conditions": "无法读取、used>0 且无外部配置 → UNKNOWN",
    },
    {
        "metric_id": "local.filesystem.used_percent",
        "name": "磁盘使用率",
        "command": "df -P -T /（根文件系统；按文件系统取最大值）",
        "timeout_sec": 10,
        "parser": "parse_filesystem_used_percent",
        "unit": "%",
        "source_anchor": (
            "9 份巡检手册 P0 磁盘行（ES T5R5、Kafka T5R9、Mysql T5R9、Nacos T5R9、"
            "Rabbitmq T5R10、Redis T5R10、Rocketmq T5R10、Nginx T5R10、Tomcat T5R8）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线（75/85/95 分层）+ 外部配置覆盖",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.filesystem.used_percent"],
        "conflicts": ["C1（Nginx/Tomcat 建议线 80% 差异，外部配置覆盖）",
                      "C6（ES >90% 严重告警层并入 CRIT）"],
        "doc_baseline": "<75% → OK（Nginx/Tomcat <80%，C1）；75–85% → WARN（关注）；"
                        ">85% → CRIT（告警）；>95% → CRIT（故障风险）",
        "unknown_conditions": "根文件系统不可读或 df 不可用 → UNKNOWN",
    },
    {
        "metric_id": "local.filesystem.inode_used_percent",
        "name": "inode 使用率",
        "command": "df -P -i /（根文件系统；按文件系统取最大值）",
        "timeout_sec": 10,
        "parser": "parse_filesystem_inode_used_percent",
        "unit": "%",
        "source_anchor": (
            "9 份巡检手册 P0 磁盘行（ES T5R5、Kafka T5R9、Mysql T5R9、Nacos T5R9、"
            "Rabbitmq T5R10、Redis T5R10、Rocketmq T5R10、Nginx T5R10、Tomcat T5R8）；"
            + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线 + 外部配置覆盖；≥80% 数值边界缺失 → 默认 UNKNOWN",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.filesystem.inode_used_percent"],
        "conflicts": ["C5（≥80% 仅描述“接近耗尽”未给数值边界）"],
        "doc_baseline": "<80% → OK（全部手册一致）；≥80% → 缺失 → UNKNOWN"
                        "（外部配置可覆盖）",
        "unknown_conditions": "根文件系统不可读、df 不可用、≥80% 无外部配置 → UNKNOWN",
    },
    {
        "metric_id": "local.logs.key_evidence",
        "name": "关键日志证据",
        "command": "tail -300 <profile 日志路径> | egrep -i '<profile 关键词>'"
                   "（路径/关键词为产品 profile 配置）",
        "timeout_sec": 15,
        "parser": "parse_logs_key_evidence",
        "unit": "匹配行数 + 关键词分布",
        "source_anchor": (
            "9 份巡检手册 P0 关键日志行（ES T5R11、Kafka T5R11、Mysql T5R11、"
            "Nacos T5R10、Rabbitmq T5R11、Redis T5R11、Rocketmq T5R11、Nginx T5R11、"
            "Tomcat T5R5）；" + _MANUAL_SHA
        ),
        "threshold_layer": "文档基线（无新增不可解释 ERROR/FATAL → OK）+ 产品 profile 关键词集配置",
        "threshold_rule_ids": [f"{_RULE_PREFIX}:local.logs.key_evidence"],
        "conflicts": ["C10（命中后按产品手册判定，冲突未解决 → UNKNOWN）"],
        "doc_baseline": "无新增不可解释 ERROR/FATAL、WARN 均可解释 → OK；OOM/磁盘满/连接耗尽/"
                        "主从异常/认证失败等 → WARN 或 CRIT（按产品手册）",
        "unknown_conditions": "日志不可读（不作为 OK）、关键词集无配置 → UNKNOWN",
    },
]

_METRICS_BY_ID = {m["metric_id"]: m for m in METRICS}

# 注册表字段契约（tests/test_metrics.py 校验每个条目的键集）
REQUIRED_FIELDS = (
    "metric_id",
    "name",
    "command",
    "timeout_sec",
    "parser",
    "unit",
    "source_anchor",
    "threshold_layer",
    "threshold_rule_ids",
    "conflicts",
    "doc_baseline",
    "unknown_conditions",
)

ALL_METRIC_IDS = tuple(m["metric_id"] for m in METRICS)


def get_metric(metric_id):
    """按 metric_id 查单条指标定义；不存在返回 None（--info 使用）。"""
    return _METRICS_BY_ID.get(metric_id)


def iter_metrics():
    """按注册表顺序迭代全部指标定义。"""
    return iter(METRICS)


def count_metrics():
    """已实现指标总数（当前恒为 10）。"""
    return len(METRICS)
