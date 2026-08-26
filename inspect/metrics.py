"""10 个共同 P0 指标注册表（linux-common-p0-v1，T-101）。

每条指标定义锚定 docs/specs/local-metrics-requirements.md §5（字段与来源锚点）
与 docs/specs/technical-design.md §5.2（采集命令、超时、解析器约定）。
本模块只提供**定义数据**，不执行任何采集命令、不做阈值判定
（阈值判定属 T-102 基线文件/T-104 normalize 范围；规则 ID 仅作引用）。

字段契约（tests/test_metrics.py 机械校验，增删需同步合同）：
  metric_id         版本化标识（如 local.cpu.utilization）
  name              中文名称（--list-metrics 展示）
  command           采集命令（MR §5 数据源列只读转译，含 <profile> 配置占位）
  timeout_sec       默认采集超时上限（CLI 会由 inspect.conf timeout 统一覆盖）
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
        "unit": "1分钟系统负载（数值）",
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
        "conflicts": [],
        "doc_baseline": "<10% → CRIT；10% ≤ available_percent < 20% → WARN；≥20% → OK",
        "unknown_conditions": "free 不可用或解析失败 → UNKNOWN",
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
        "command": "df -hT（全部文件系统；按文件系统取最大值）",
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
        "command": "df -i（全部文件系统；按文件系统取最大值）",
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


# --------------------------------------------------------------------------
# Nginx 中间件指标（nginx-p0-v1，安徽农金Nginx、Keepalived运维巡检手册v1.0）
# --------------------------------------------------------------------------
_NGINX_RULE_PREFIX = "nginx-p0-v1"
_NGINX_ANCHOR = (
    "安徽农金Nginx、Keepalived运维巡检手册v1.0.docx（P0 必看指标表：Nginx本节点服务/"
    "配置有效性/端口与本地访问/关键日志；P1 关注指标表：连接状态/访问日志状态码/"
    "配置基线/安全配置基线）；" + _MANUAL_SHA
)
_NGINX_DOCX = "安徽农金Nginx、Keepalived运维巡检手册v1.0.docx"

NGINX_METRICS = [
    {
        "metric_id": "local.nginx.process.present",
        "name": "Nginx 进程存在性",
        "command": "ps -eo pid=,comm=,args= | grep -E '^[[:space:]]*[0-9]+[[:space:]]+nginx[[:space:]]+nginx: (master|worker) process'",
        "timeout_sec": 10,
        "parser": "parse_process_present",
        "unit": "布尔（present/absent）+ 匹配行数",
        "source_anchor": (
            "P0 指标表「Nginx本节点服务」行（ps 的 comm 列必须为 nginx，args 列必须为 "
            "nginx master/worker process；命令文本中出现 nginx 不算运行）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（进程存在=正常；未运行=CRIT）+ nginx 白名单（白名单内未运行 → CRIT 未运行）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.process.present"],
        "conflicts": [],
        "doc_baseline": "进程存在 → OK；进程不存在 → CRIT（未运行/故障）；白名单外主机未运行 → 跳过该主机 nginx 指标",
        "unknown_conditions": "无权限或 pgrep 不可用 → UNKNOWN，继续其余指标",
    },
    {
        "metric_id": "local.nginx.version",
        "name": "Nginx 版本",
        "command": "{nginx_bin} -v 2>&1",
        "timeout_sec": 10,
        "parser": "parse_nginx_version",
        "unit": "版本号",
        "source_anchor": (
            "P0 指标表「Nginx版本」行（从运行中 Nginx master 进程解析可执行文件，执行 nginx -v，"
            "取得实际 nginx/x.y.z）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "inspect.conf nginx_version 版本白名单（实际版本一致=正常；不一致=CRIT）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.version"],
        "conflicts": [],
        "doc_baseline": "实际运行版本属于 inspect.conf 的 nginx_version 候选值 → OK；实际版本不在候选值内 → CRIT",
        "unknown_conditions": "无法发现运行中的 Nginx 可执行文件、nginx -v 无版本输出或未配置 nginx_version → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.config.valid",
        "name": "Nginx 配置有效性",
        "command": "{nginx_bin} -t -e {nginx_error_log} -c {nginx_conf}",
        "timeout_sec": 10,
        "parser": "parse_nginx_config_valid",
        "unit": "枚举（valid/invalid）",
        "source_anchor": (
            "P0 指标表「Nginx配置有效性」行（/usr/sbin/nginx -e error.log -c "
            "nginx.conf -t；返回 syntax is ok 和 test is successful）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（语法通过=正常；语法失败=CRIT）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.config.valid"],
        "conflicts": [],
        "doc_baseline": "syntax is ok + test is successful → OK；语法失败/文件缺失/端口冲突/权限错误 → CRIT（故障）",
        "unknown_conditions": "nginx 可执行文件不可用、无权限读取配置 → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.port.listening",
        "name": "Nginx 端口监听与本地访问",
        "command": (
            "netstat -lntp | grep ':{nginx_port}'; "
            "curl -sS -I --connect-timeout 3 http://{nginx_listener_host}:{nginx_port}/ | head -n 1"
        ),
        "timeout_sec": 10,
        "parser": "parse_nginx_port_listening",
        "unit": "枚举（listening/reachable）+ 本地 HTTP 状态",
        "source_anchor": (
            "P0 指标表「Nginx端口与本地访问」行（netstat -lntp | grep ':8010'；"
            "curl -sS -I --connect-timeout 3 http://{nginx_listener_host}:8010/）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（监听且本地可访问=正常；不监听/连接失败/5xx=CRIT）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.port.listening"],
        "conflicts": [],
        "doc_baseline": "端口 LISTEN 且本地 HTTP 返回 200/302/401/403 等可解释状态 → OK；端口不监听、连接超时/拒绝或持续 5xx → CRIT（故障）",
        "unknown_conditions": "netstat/curl 不可用或无法读取 → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.error_log.key_evidence",
        "name": "Nginx 关键日志",
                "command": (
            "ls -1 {nginx_error_log} 2>/dev/null; "
            "tail -n 1000 {nginx_error_log} | egrep -i "
            "'emerg|alert|crit|error|permission denied|bind\\(|connect\\(\\) failed|"
            "upstream timed out' | tail -n 20"
        ),
        "timeout_sec": 15,
        "parser": "parse_nginx_error_log",
        "unit": "命中行数 + 严重度分布",
        "source_anchor": (
            "P0 指标表「关键日志」行（tail -n 100 error.log；egrep -i 'emerg|alert|crit|"
            "error|permission denied|bind(|connect() failed|upstream timed out'）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（无持续 emerg/alert/crit/error=正常；有命中=关注）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.error_log.key_evidence"],
        "conflicts": [],
        "doc_baseline": "无命中 → OK；命中 emerg/alert/crit/error 等 → WARN（记录时间点与错误内容，优先处理）",
        "unknown_conditions": "日志不可读（不作为 OK）→ UNKNOWN",
    },
    {
        "metric_id": "local.nginx.access_log.status_codes",
        "name": "访问日志状态码",
        "command": (
            "ls -1 {nginx_access_log} 2>/dev/null; "
            "tail -n 1000 {nginx_access_log} | grep -E ' [1-5][0-9][0-9] '"
        ),
        "timeout_sec": 15,
        "parser": "parse_nginx_access_log_status_codes",
        "unit": "5xx 命中数 + 状态码分布",
        "source_anchor": (
            "P1 指标表「访问日志状态码」行（tail -n 1000 access.log | awk '{print $9}' "
            "| sort | uniq -c；5xx 无持续增长）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（2xx/3xx 为主、5xx 无持续增长=正常；5xx 命中=关注）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.access_log.status_codes"],
        "conflicts": [],
        "doc_baseline": "5xx=0 → OK；5xx>0 → WARN（记录 URL/来源 IP/状态码/时间段，关联 error.log 处理）",
        "unknown_conditions": "访问日志不可读 → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.config.baseline",
        "name": "Nginx 配置基线",
        "command": (
            "ls -1 {nginx_conf} 2>/dev/null; "
            "grep -E 'worker_processes|worker_rlimit_nofile|worker_connections|"
            "use epoll|multi_accept|keepalive_timeout|client_max_body_size|limit_req|"
            "limit_conn' {nginx_conf}"
        ),
        "timeout_sec": 10,
        "parser": "parse_nginx_config_baseline",
        "unit": "关键指令命中集合（worker_processes/worker_connections/keepalive_timeout 等）",
        "source_anchor": (
            "P1 指标表「Nginx配置基线」行（grep -E 'worker_processes|worker_rlimit_nofile|"
            "worker_connections|use epoll|multi_accept|keepalive_timeout|client_max_body_size|"
            "limit_req|limit_conn' nginx.conf）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（关键指令齐全=正常；配置漂移=关注）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.config.baseline"],
        "conflicts": [],
        "doc_baseline": "worker_processes/worker_connections/keepalive_timeout 等核心指令存在 → OK；缺失 → WARN（配置漂移，记录差异与变更依据）",
        "unknown_conditions": "配置文件不可读 → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.security.baseline",
        "name": "安全配置基线",
        "command": (
            "ls -1 {nginx_conf} 2>/dev/null; "
            "grep -E 'server_tokens|autoindex|X-Frame-Options|X-Content-Type-Options|"
            "Content-Security-Policy|request_method' {nginx_conf}"
        ),
        "timeout_sec": 10,
        "parser": "parse_nginx_security_baseline",
        "unit": "安全指令命中集合（server_tokens/autoindex/安全响应头）",
        "source_anchor": (
            "P1 指标表「安全配置基线」行（grep -E 'server_tokens|autoindex|X-Frame-Options|"
            "X-Content-Type-Options|Content-Security-Policy|request_method' nginx.conf）；" + _NGINX_ANCHOR
        ),
        "threshold_layer": "文档基线（server_tokens off + autoindex off=正常；安全配置缺失=关注）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.security.baseline"],
        "conflicts": [],
        "doc_baseline": "server_tokens off 且 autoindex off → OK；缺失 → WARN（记录风险，按安全加固要求补齐）",
        "unknown_conditions": "配置文件不可读 → UNKNOWN",
    },
    # Nginx v2 facts use canonical DOCX anchors. Undefined capacity and
    # certificate-age boundaries remain gaps rather than invented thresholds.
    {
        "metric_id": "local.nginx.http.reachability",
        "name": "Nginx HTTP 可达性",
        "command": "curl -sS --connect-timeout 3 -I http://{nginx_listener_host}:{nginx_port}/ | head -n 1",
        "timeout_sec": 10,
        "parser": "parse_nginx_http_reachability",
        "unit": "布尔（reachable）+ HTTP 状态码",
        "source_anchor": f"DOCX:{_NGINX_DOCX}:TABLE6-R4",
        "threshold_layer": "文档基线（本地 HTTP 可达性与状态码）",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.http.reachability"],
        "conflicts": [],
        "doc_baseline": "返回 2xx/3xx/401/403 等可解释状态 → OK；明确 5xx → CRIT",
        "unknown_conditions": "无法取得 HTTP 响应、连接失败或 curl 不可用 → UNKNOWN",
    },
    {
        "metric_id": "local.nginx.fd.process.limits",
        "name": "Nginx 文件描述符与进程限制",
        "command": "ps -eo pid=,comm=,args= | grep -E '^[[:space:]]*[0-9]+[[:space:]]+nginx[[:space:]]+nginx: master process'",
        "timeout_sec": 10,
        "parser": "parse_nginx_fd_process_limits",
        "unit": "nofile/max_processes 限制值",
        "source_anchor": f"DOCX:{_NGINX_DOCX}:TABLE7-R7",
        "threshold_layer": "用户授权的产品补充阈值（非 DOCX-derived）：nofile >=65535/32768、max_processes >=4096/2048，按最高严重度聚合",
        "threshold_rule_ids": [f"{_NGINX_RULE_PREFIX}:local.nginx.fd.process.limits"],
        "conflicts": [],
        "doc_baseline": "用户授权的产品补充阈值（非 DOCX-derived）：nofile >=65535 OK、32768..65534 WARN、<32768 CRIT；max_processes >=4096 OK、2048..4095 WARN、<2048 CRIT；两维按最高严重度聚合",
        "unknown_conditions": "Nginx master 或 /proc 限制输出不可读，或 nofile/max_processes 缺失/无效 → UNKNOWN",
    },
]

# 阈值规则 ID 前缀（nginx-p0-v1）
NGINX_RULE_PREFIX = _NGINX_RULE_PREFIX

METRICS.extend(NGINX_METRICS)
NGINX_METRIC_IDS = tuple(metric["metric_id"] for metric in NGINX_METRICS)


# --------------------------------------------------------------------------
# Keepalived 中间件指标（keepalived-p0-v1）
# --------------------------------------------------------------------------
_KEEPALIVED_RULE_PREFIX = "keepalived-p0-v1"
_KEEPALIVED_ANCHOR = (
    "安徽农金Nginx、Keepalived运维巡检手册v1.0.docx（P0 必看指标表：Keepalived本节点服务/"
    "VIP绑定状态/VIP访问/配置基线/健康检查脚本/关键日志；P1 关注指标表：Keepalived能力与漂移稳定性）；"
    "定位：T5R4/T5R6；"
    + _MANUAL_SHA
)

KEEPALIVED_METRICS = [
    {
        "metric_id": "local.keepalived.process.present",
        "name": "Keepalived 进程存在性",
        "command": "ps -eo pid=,comm=,args= | grep -E '^[[:space:]]*[0-9]+[[:space:]]+keepalived[[:space:]]'",
        "timeout_sec": 10,
        "parser": "parse_process_present",
        "unit": "布尔（present/absent）+ 匹配行数",
        "source_anchor": "P0 指标表「Keepalived本节点服务」行（ps 的 comm 列必须为 keepalived；命令文本中出现 keepalived 不算运行）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（Keepalived 主进程/VRRP 子进程存在=正常；未运行=CRIT）+ keepalived 白名单",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.process.present"],
        "conflicts": [],
        "doc_baseline": "发现 Keepalived 进程 → OK；未发现 → 白名单主机 CRIT「未运行」，非白名单主机跳过 Keepalived 指标",
        "unknown_conditions": "无权限或 pgrep 不可用 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.version",
        "name": "Keepalived 版本",
        "command": "{keepalived_bin} -v 2>&1",
        "timeout_sec": 10,
        "parser": "parse_keepalived_version",
        "unit": "版本号",
        "source_anchor": "环境信息「Keepalived版本」行（以 keepalived -v 输出为准）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "inspect.conf keepalived_version 版本基线（实际版本一致=正常；不一致=CRIT）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.version"],
        "conflicts": [],
        "doc_baseline": "运行中的 Keepalived 版本命中 inspect.conf keepalived_version 候选值 → OK；不一致 → CRIT",
        "unknown_conditions": "无法发现运行中的 Keepalived 可执行文件、-v 无版本输出或未配置 keepalived_version → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.vip.bound",
        "name": "VIP 绑定状态",
        "command": "ip -brief addr；解析 {keepalived_conf} 中 virtual_ipaddress 与 state",
        "timeout_sec": 10,
        "parser": "parse_keepalived_vip_bound",
        "unit": "枚举（bound/unbound）+ VIP/角色",
        "source_anchor": "P0 指标表「VIP绑定状态」行（ip -brief addr；ip addr show dev interface）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（MASTER 持有 VIP、BACKUP 不持有 VIP）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.vip.bound"],
        "conflicts": ["单主机巡检无法单独证明另一台节点是否同时持有 VIP"],
        "doc_baseline": "从实际 Keepalived 配置读取 state/VIP；MASTER 应持有 VIP，BACKUP 正常不持有 VIP；符合角色预期 → OK；角色异常、MASTER 无 VIP 或 BACKUP 持有 VIP → CRIT",
        "unknown_conditions": "运行配置不可发现、virtual_ipaddress 未配置、ip 不可用或无法读取地址 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.vip.access",
        "name": "VIP 访问",
        "command": "curl -sS -I --connect-timeout {timeout} --max-time {timeout} http://{keepalived_vip}:{keepalived_port}/",
        "timeout_sec": 10,
        "parser": "parse_keepalived_vip_access",
        "unit": "枚举（reachable/unreachable）+ HTTP 状态",
        "source_anchor": "P0 指标表「VIP访问」行（仅在目标主机本机执行 curl -sS -I http://配置VIP:端口/；VIP 地址只用于配置/绑定核对）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（VIP 可访问且非 5xx=正常；无法访问/5xx=CRIT）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.vip.access"],
        "conflicts": [],
        "doc_baseline": "优先读取配置中的 virtual_ipaddress 确认 VIP 配置，再使用 inspect.conf keepalived_port；为避免跨主机访问，HTTP 只在目标主机本机请求 http://配置VIP:端口/；返回 200/3xx/401/403 等可解释状态 → OK；连接失败或 5xx → CRIT",
        "unknown_conditions": "端口无法从 inspect.conf 得到、curl 不可用或本机请求超时 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.config.baseline",
        "name": "Keepalived 配置基线",
        "command": "egrep 'state|interface|virtual_router_id|priority|advert_int|virtual_ipaddress|script|track_script' {keepalived_conf}",
        "timeout_sec": 10,
        "parser": "parse_keepalived_config_baseline",
        "unit": "关键指令命中集合",
        "source_anchor": "P0 指标表「Keepalived配置基线」行（egrep state/interface/virtual_router_id/priority/advert_int/virtual_ipaddress/script/track_script）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（VRRP 角色、网卡、VRID、优先级、VIP、健康检查配置齐全=正常）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.config.baseline"],
        "conflicts": [],
        "doc_baseline": "配置中同时存在 state、interface、virtual_router_id、priority、advert_int、virtual_ipaddress、script、track_script 等关键项 → OK；缺失 → WARN，表示可能配置漂移",
        "unknown_conditions": "配置文件不可发现、不可读或 grep 不可用 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.healthcheck.script",
        "name": "健康检查脚本",
        "command": "解析 {keepalived_conf} 中 vrrp_script 的 script 路径；ls -l；test -x",
        "timeout_sec": 10,
        "parser": "parse_keepalived_healthcheck",
        "unit": "枚举（present/executable）",
        "source_anchor": "P0 指标表「健康检查脚本」行（ls -l /opt/keepalived/scripts/check_nginx.sh；echo $?）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（脚本存在且可执行=正常；缺失/不可执行=CRIT）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.healthcheck.script"],
        "conflicts": [],
        "doc_baseline": "从实际配置解析 track_script 引用的脚本；脚本存在且可执行（建议权限 750 或更严格）→ OK；缺失或不可执行 → CRIT。为安全起见巡检只做静态权限检查，不执行现场脚本",
        "unknown_conditions": "配置不可发现、未找到 script 引用或路径不可判定 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.error_log.key_evidence",
        "name": "Keepalived 关键日志",
        "command": "tail -n 1000 {keepalived_log} | egrep -i 'Entering MASTER|Entering BACKUP|Entering FAULT|script.*failed|VRRP'",
        "timeout_sec": 15,
        "parser": "parse_keepalived_error_log",
        "unit": "命中行数 + 事件分布",
        "source_anchor": "P0 指标表「关键日志」行（tail keepalived.log；egrep Entering MASTER/BACKUP/FAULT/script failed/VRRP）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（无 FAULT/脚本失败且无频繁角色切换=正常）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.error_log.key_evidence"],
        "conflicts": [],
        "doc_baseline": "日志末尾 1000 行无 FAULT、健康检查脚本失败且 MASTER/BACKUP 切换不频繁 → OK；发现 FAULT/脚本失败 → CRIT；短时间反复切换 → WARN",
        "unknown_conditions": "日志路径无法发现、文件不可读或日志尚未配置 → UNKNOWN",
    },
    {
        "metric_id": "local.keepalived.capability.stability",
        "name": "Keepalived 能力与漂移稳定性",
        "command": "getcap {keepalived_bin}；systemctl show keepalived-opt -p AmbientCapabilities -p CapabilityBoundingSet；tail -n 50 {keepalived_log}",
        "timeout_sec": 15,
        "parser": "parse_keepalived_capability_stability",
        "unit": "枚举（capability/stability）",
        "source_anchor": "P1 指标表「Keepalived能力与漂移稳定性」行（getcap、systemctl capability、日志切换/FAULT/脚本失败）；" + _KEEPALIVED_ANCHOR,
        "threshold_layer": "文档基线（具备 cap_net_admin/cap_net_raw 且无故障切换=正常）",
        "threshold_rule_ids": [f"{_KEEPALIVED_RULE_PREFIX}:local.keepalived.capability.stability"],
        "conflicts": [],
        "doc_baseline": "运行二进制具备 cap_net_admin、cap_net_raw 等网络能力，且最近日志无 FAULT/脚本失败/频繁切换 → OK；能力缺失或故障事件 → CRIT；日志缺失无法判断稳定性 → UNKNOWN",
        "unknown_conditions": "getcap/systemctl/日志不可用，或运行二进制/日志路径无法发现 → UNKNOWN",
    },
]

KEEPALIVED_RULE_PREFIX = _KEEPALIVED_RULE_PREFIX
METRICS.extend(KEEPALIVED_METRICS)
KEEPALIVED_METRIC_IDS = tuple(metric["metric_id"] for metric in KEEPALIVED_METRICS)

# --------------------------------------------------------------------------
# Elasticsearch 中间件指标（elasticsearch-p0-p1-v1）
# --------------------------------------------------------------------------
_ELASTICSEARCH_RULE_PREFIX = "elasticsearch-p0-p1-v1"
_ELASTICSEARCH_ANCHOR = (
    "安徽农金Elasticsearch运维巡检手册v1.0.docx（P0 表62、P1 表65；"
    "定位：T5R3/T5R4/T5R5/T5R11/T6R1；Elasticsearch 8.17.0 HTTPS API/9200、"
    "传输端口9300、/opt/elasticsearch 默认布局）；"
    + _MANUAL_SHA
)


def _es_metric(metric_id, name, command, parser, unit, baseline, unknown, *, timeout=10):
    """Create a fully populated metric definition for the ES adapter."""
    return {
        "metric_id": metric_id,
        "name": name,
        "command": command,
        "timeout_sec": timeout,
        "parser": parser,
        "unit": unit,
        "source_anchor": _ELASTICSEARCH_ANCHOR,
        "threshold_layer": "Elasticsearch 文档基线（可由 thresholds-override.yml 覆盖）",
        "threshold_rule_ids": [f"{_ELASTICSEARCH_RULE_PREFIX}:{metric_id}"],
        "conflicts": [],
        "doc_baseline": baseline,
        "unknown_conditions": unknown,
    }


ELASTICSEARCH_METRICS = [
    _es_metric("local.elasticsearch.process.present", "Elasticsearch 进程存在性",
                 "ps -eo pid=,comm=,args= | grep -E '^[[:space:]]*[0-9]+[[:space:]]+(java[[:space:]].*org\\.elasticsearch\\.bootstrap\\.Elasticsearch|elasticsearch[[:space:]])'",
                "parse_process_present", "布尔（present/absent）+ 匹配行数",
                "发现运行中的 Elasticsearch JVM/启动脚本 → OK；白名单主机未运行 → CRIT；非白名单主机跳过",
                "pgrep 不可用或无权限 → UNKNOWN"),
    _es_metric("local.elasticsearch.version", "Elasticsearch 版本",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/",
                "parse_elasticsearch_version", "版本号",
                "通过运行实例 HTTPS 根 API 读取 version.number；命中 inspect.conf elasticsearch_version → OK；不一致 → CRIT",
                "进程未运行、API 未授权/连接失败、根 API 无 version.number 或未配置版本基线 → UNKNOWN"),
    _es_metric("local.elasticsearch.cluster.health", "集群健康",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cluster/health?pretty",
                "parse_elasticsearch_cluster_health", "枚举（green/yellow/red）+ 节点数 + 分片百分比",
                "status=green、节点数达到 elasticsearch_expected_nodes、active_shards_percent=100 → OK；yellow → WARN；red/节点严重不足 → CRIT",
                "HTTP 401/403/连接失败、返回非 JSON 或无法发现端点 → UNKNOWN"),
    _es_metric("local.elasticsearch.nodes.online", "集群在线节点数",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/nodes?v&h=name,ip,node.role,master,heap.percent,cpu,load_1m,disk.used_percent",
                "parse_elasticsearch_nodes", "在线节点数",
                "在线节点数达到 elasticsearch_expected_nodes → OK；少 1 台 → WARN；少 2 台及以上 → CRIT",
                "API 未授权、返回为空/格式异常或未配置期望节点数 → UNKNOWN"),
    _es_metric("local.elasticsearch.nodes.cpu", "Elasticsearch 节点 CPU",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/nodes?v&h=name,ip,cpu,load_1m,load_5m,load_15m",
                "parse_elasticsearch_nodes_cpu", "%（节点最大 CPU）",
                "节点最大 CPU <80% → OK；80%–90% → WARN；>90% → CRIT",
                "API 未授权、无节点行或 CPU 字段不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.nodes.memory", "Elasticsearch 节点内存",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/nodes?v&h=name,heap.percent,ram.percent",
                "parse_elasticsearch_nodes_memory", "%（最大 heap/ram）",
                "heap <75% 且 ram <90% → OK；heap 75%–85% 或 ram 90%–95% → WARN；heap >85% 或 ram >95% → CRIT",
                "API 未授权、无节点行或 heap/ram 字段不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.nodes.disk", "Elasticsearch 节点磁盘",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/allocation?v",
                "parse_elasticsearch_nodes_disk", "%（节点最大 disk.percent）",
                "disk.percent <75% → OK；75%–85% → WARN；>85% → CRIT（>95% 有 flood-stage 只读风险）",
                "API 未授权、无 allocation 行或 disk.percent 不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.disk.watermark", "磁盘水位线",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} 'https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cluster/settings?include_defaults=true&filter_path=**.watermark*'",
                "parse_elasticsearch_watermark", "水位线配置与当前最高磁盘使用率",
                "能读取 low/high/flood_stage 配置且当前磁盘未越过 high → OK；接近/超过 high → WARN/CRIT",
                "API 未授权、设置返回非 JSON 或无法关联磁盘数据 → UNKNOWN"),
    _es_metric("local.elasticsearch.shards.unassigned", "未分配分片",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/shards?v&h=index,shard,prirep,state,node,unassigned.reason",
                "parse_elasticsearch_shards", "未分配/初始化分片数",
                "无 UNASSIGNED/持续 INITIALIZING → OK；副本未分配 → WARN；主分片未分配 → CRIT",
                "API 未授权、返回为空或分片表不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.service.port", "Elasticsearch 服务与端口",
                "ps -ef | grep '[e]lasticsearch'; ss -tlnp | grep -E ':{elasticsearch_http_port}|:{elasticsearch_transport_port}'",
                "parse_elasticsearch_service_port", "进程 + HTTP/Transport 端口状态",
                "运行进程存在且 9200 HTTP、9300 Transport（或 inspect.conf 配置端口）均监听 → OK；任一缺失 → CRIT",
                "ps/ss 不可用、端口未配置或输出无法核对 → UNKNOWN"),
    _es_metric("local.elasticsearch.heap.gc", "Elasticsearch Heap/GC",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/nodes?v&h=name,heap.percent; tail -n 200 {elasticsearch_gc_log} | grep -Ei 'Pause|Full|OutOfMemory|heap'",
                "parse_elasticsearch_heap_gc", "最大 heap 百分比 + GC/OOM 命中数",
                "heap <75% 且无 Full GC/OOM → OK；heap 75%–85% 或 Full GC → WARN；OOM/heap >85% → CRIT",
                "API/GC 日志不可读或路径无法发现 → UNKNOWN", timeout=15),
    _es_metric("local.elasticsearch.thread_pool.rejected", "线程池拒绝",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/thread_pool/search,write?v&h=node_name,name,active,queue,rejected,completed",
                "parse_elasticsearch_thread_pool", "rejected/queue 总数",
                "search/write rejected=0 且 queue=0 → OK；出现排队或拒绝 → WARN；持续大量拒绝 → CRIT",
                "API 未授权、线程池表为空或字段不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.cluster.settings", "集群动态设置",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} 'https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cluster/settings?flat_settings=true&pretty'",
                "parse_elasticsearch_cluster_settings", "动态设置检查结果",
                "不存在 allocation.enable=none/primaries 或临时 rebalance 禁用 → OK；发现遗留限制 → WARN",
                "API 未授权、返回非 JSON 或无法读取设置 → UNKNOWN"),
    _es_metric("local.elasticsearch.discovery.config", "集群发现配置",
                "grep -E 'discovery.seed_hosts|cluster.initial_master_nodes|network.host|node.name' {elasticsearch_conf}",
                "parse_elasticsearch_discovery_config", "seed_hosts/initial_master_nodes 配置检查",
                "seed_hosts 覆盖规划节点且集群形成后不再保留 cluster.initial_master_nodes → OK；缺失/漂移 → WARN",
                "elasticsearch.yml 不存在、不可读或关键项无法解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.indices.health", "索引健康与规模",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} 'https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_cat/indices?v&h=health,index,pri,rep,docs.count,store.size&s=store.size:desc'",
                "parse_elasticsearch_indices", "索引数 + red/yellow 数",
                "无 red/yellow 索引 → OK；yellow → WARN；red → CRIT；结果同时展示索引规模",
                "API 未授权、返回为空或索引表不可解析 → UNKNOWN"),
    _es_metric("local.elasticsearch.slowlog.key_evidence", "慢查询/写入日志",
                "ls -1 {elasticsearch_log}/*slowlog* 2>/dev/null; tail -n 100 {elasticsearch_log}/*slowlog* 2>/dev/null",
                "parse_elasticsearch_slowlog", "慢日志文件数 + 命中行数",
                "慢日志无持续命中 → OK；发现慢查询/慢写入记录 → WARN；慢日志未启用时明确说明而不误报",
                "日志目录无法发现、不可读或命令不可用 → UNKNOWN", timeout=15),
    _es_metric("local.elasticsearch.security.accounts", "安全账号与权限",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_security/user?pretty; curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_security/role?pretty",
                "parse_elasticsearch_security", "用户/角色数量 + superuser 风险",
                "无未知高权限账号、应用不使用 elastic 超级用户 → OK；发现非基线 superuser → WARN",
                "安全 API 未授权或返回非 JSON → UNKNOWN"),
    _es_metric("local.elasticsearch.certificate.validity", "HTTPS 证书有效期",
                "openssl x509 -in {elasticsearch_cert} -noout -dates -checkend 2592000",
                "parse_elasticsearch_certificate", "证书剩余天数",
                "证书未过期且剩余 ≥30 天 → OK；剩余 <30 天 → WARN；已过期/检查失败 → CRIT",
                "证书路径无法从进程/config/inspect.conf 发现、openssl 不可用或格式异常 → UNKNOWN"),
    _es_metric("local.elasticsearch.snapshot.repository", "快照仓库",
                "curl -sS --connect-timeout {timeout} --max-time {timeout} {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_snapshot/_all?pretty; curl -sS --connect-timeout {timeout} --max-time {timeout} -X POST {elasticsearch_auth} https://{elasticsearch_listener_host}:{elasticsearch_http_port}/_snapshot/{elasticsearch_snapshot_repo}/_verify?pretty",
                "parse_elasticsearch_snapshot", "仓库数量 + verify 状态",
                "存在已注册仓库且 _verify 成功 → OK；仓库缺失或 verify 失败 → WARN/CRIT",
                "API 未授权、仓库名未配置或返回非 JSON → UNKNOWN"),
    _es_metric("local.elasticsearch.system.parameters", "Elasticsearch 系统参数",
                "cat /proc/sys/vm/max_map_count; free -m; su - {elasticsearch_system_user} -c 'ulimit -n; ulimit -u; ulimit -l'",
                "parse_elasticsearch_system_parameters", "max_map_count/swap/nofile/nproc/memlock",
                "max_map_count=262144、Swap=0、nofile≥65535、nproc≥4096、memlock=unlimited → OK；任一不满足 → WARN/CRIT",
                "系统文件或运行用户不可读取、命令缺失 → UNKNOWN"),
]

ELASTICSEARCH_RULE_PREFIX = _ELASTICSEARCH_RULE_PREFIX
METRICS.extend(ELASTICSEARCH_METRICS)

# --------------------------------------------------------------------------
# Additional middleware P0/P1 facts
# --------------------------------------------------------------------------

def _middleware_metric(
    metric_id: str,
    name: str,
    command: str,
    manual: str,
    priority: str,
    baseline: str,
    *,
    unit: str = "原始命令输出",
) -> dict:
    """Build one document-backed fact without duplicating Linux basics.

    The command is the redacted text from the corresponding manual.  It is
    retained as evidence/report source text; execution still goes through the
    independent runner allow-list.
    """
    typed_prefixes = (
        "local.kafka.", "local.mysql.", "local.nacos.", "local.rabbitmq.",
        "local.redis.", "local.rocketmq.", "local.tomcat.", "local.zookeeper.",
    )
    typed_keepalived = {
        "local.keepalived.vip.present",
        "local.keepalived.vrrp.role",
        "local.keepalived.health_check.status",
    }
    numeric_units = {
        "local.kafka.under_replicated_partitions": "分区数",
        "local.kafka.under_min_isr": "分区数",
        "local.kafka.topic.replica_distribution": "分区数",
        "local.kafka.consumer.lag": "消息数",
        "local.zookeeper.ports.health": "端口数",
        "local.zookeeper.mntr.health": "毫秒",
        "local.mysql.replication.lag": "秒",
        "local.mysql.connection.pressure": "百分比",
        "local.mysql.error_log.key_evidence": "条数",
        "local.mysql.slow_query.key_evidence": "条数",
        "local.mysql.innodb.waits": "数量",
        "local.mysql.buffer_pool.hit_ratio": "百分比",
        "local.mysql.sql.digest": "线程数",
        "local.nacos.core_ports.health": "端口数",
        "local.nacos.cluster.nodes": "节点数",
        "local.nacos.error_log": "条数",
        "local.nacos.http.errors": "条数",
        "local.nacos.thread.fd.pressure": "文件句柄数",
        "local.nacos.log.data.retention": "文件数",
        "local.nacos.metrics.collection": "指标行数",
        "local.nacos.database.errors": "条数",
        "local.nacos.system.parameters": "文件句柄数",
        "local.rabbitmq.cluster.nodes": "节点数",
        "local.rabbitmq.queue.backlog": "消息数",
        "local.rabbitmq.connection.pressure": "数量",
        "local.rocketmq.consumer.lag": "消息数",
        "local.rocketmq.core_ports.health": "端口数",
        "local.tomcat.http.health": "端口数",
        "local.tomcat.access_log.errors": "条数",
        "local.tomcat.jvm.memory": "MB",
        "local.tomcat.thread_pool.pressure": "文件句柄数",
    }
    is_typed = metric_id.startswith(typed_prefixes) or metric_id in typed_keepalived
    if is_typed:
        parser = "parse_" + metric_id.removeprefix("local.").replace(".", "_")
        unit = numeric_units.get(metric_id, "布尔")
    else:
        parser = "parse_middleware_text"
    return {
        "metric_id": metric_id,
        "name": name,
        "command": command,
        "timeout_sec": 15 if "日志" in name or "log" in metric_id else 10,
        "parser": parser,
        "unit": unit,
        "source_anchor": f"DOCX:{manual}:{priority}",
        "threshold_layer": "document-baseline",
        "threshold_rule_ids": [f"{metric_id}:document-baseline"],
        "conflicts": [],
        "doc_baseline": baseline,
        "unknown_conditions": "命令、权限、认证或返回数据不可用 → UNKNOWN；不以主机通用资源指标替代本指标",
    }


_ADDITIONAL_MIDDLEWARE_METRICS = [
    _middleware_metric("local.keepalived.vip.present", "Keepalived VIP 存在性", "ip -brief addr; grep -E 'virtual_ipaddress|interface' <KEEPALIVED_CONF>", "Nginx、Keepalived运维巡检手册v1.0.docx", "P0-TABLE5", "VIP 已绑定规划接口 → OK；VIP 缺失或漂移 → CRIT"),
    _middleware_metric("local.keepalived.vrrp.role", "Keepalived VRRP 角色", "grep -E 'state|priority|virtual_router_id|interface' <KEEPALIVED_CONF>", "Nginx、Keepalived运维巡检手册v1.0.docx", "P0-TABLE5", "主备角色和 priority 符合规划且无双 MASTER → OK；角色异常/双 MASTER → CRIT"),
    _middleware_metric("local.keepalived.health_check.status", "Keepalived 健康检查", "grep -E 'track_script|script' <KEEPALIVED_CONF>; test -x <HEALTHCHECK_SCRIPT>", "Nginx、Keepalived运维巡检手册v1.0.docx", "P0-TABLE5", "健康检查脚本存在、可读可执行且无持续失败 → OK；脚本缺失/失败 → CRIT"),
    _middleware_metric("local.kafka.broker.health", "Kafka Broker 服务健康", "pgrep -fa 'kafka.Kafka'; ss -tlnp | grep ':9093'", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "Kafka 进程存在且 9093 LISTEN → OK；任一缺失 → CRIT"),
    _middleware_metric("local.kafka.controller.health", "Kafka Controller 健康", "zookeeper-shell.sh <ZK_CONNECT> get /controller", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "存在且仅有 1 个有效 Controller → OK；无 Controller → CRIT；频繁变化 → WARN"),
    _middleware_metric("local.kafka.broker.registration", "Kafka Broker 注册", "zookeeper-shell.sh 127.0.0.1:2181 get /brokers/ids/<当前broker.id>", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "当前 broker.id 在 /brokers/ids 注册且 advertised.listeners 为 SSL://<IP>:9093 → OK；缺失或使用 PLAINTEXT/9092 → CRIT"),
    _middleware_metric("local.kafka.under_replicated_partitions", "Kafka 未充分复制分区", "kafka-topics.sh --bootstrap-server <BOOTSTRAP> --command-config <SSL_CONFIG> --describe --under-replicated-partitions", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "无输出 → OK；有未充分复制分区 → WARN，持续存在为 CRIT"),
    _middleware_metric("local.kafka.under_min_isr", "Kafka ISR/不可用分区", "kafka-topics.sh --bootstrap-server <BOOTSTRAP> --command-config <SSL_CONFIG> --describe --under-min-isr-partitions; kafka-topics.sh --bootstrap-server <BOOTSTRAP> --command-config <SSL_CONFIG> --describe --unavailable-partitions", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "Under-min-ISR 或不可用分区均为空 → OK；出现 → CRIT"),
    _middleware_metric("local.kafka.topic.replica_distribution", "Kafka Topic 副本分布", "kafka-topics.sh --bootstrap-server <BOOTSTRAP> --command-config <SSL_CONFIG> --describe", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "Topic 副本数为 3、ISR 足够且 Leader 分布均衡 → OK；副本不足或 ISR 缺失 → WARN/CRIT"),
    _middleware_metric("local.kafka.consumer.lag", "Kafka Consumer Lag", "kafka-consumer-groups.sh --bootstrap-server <BOOTSTRAP> --command-config <SSL_CONFIG> --describe --all-groups", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "Lag 为 0 或在业务可接受范围内 → OK；Lag 1-100 → WARN；Lag >100 → CRIT（产品补充阈值）"),
    _middleware_metric("local.kafka.error_log", "Kafka 关键错误日志", "grep -R -iE 'ERROR|FATAL|OutOfMemory|NotLeader|UnderReplicated|IOException|Session expired' /opt/kafka/logs 2>/dev/null | tail -30", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "无持续 ERROR/FATAL/OOM/NotLeader/UnderReplicated/IOException/Session expired → OK；命中关键错误 → CRIT"),
    _middleware_metric("local.kafka.config.baseline", "Kafka 配置基线", "grep -E '^(listeners|advertised.listeners|inter.broker.listener.name|log.dirs|zookeeper.connect|default.replication.factor|min.insync.replicas|unclean.leader.election.enable|auto.create.topics.enable)' /opt/kafka/conf/server.properties", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "listeners/advertised.listeners 使用 SSL 9093，副本因子=3，min.insync.replicas=2，unclean.leader.election.enable=false，auto.create.topics.enable=false → OK；偏离 → CRIT"),
    _middleware_metric("local.kafka.ssl.certificate", "Kafka SSL 证书有效期", "find /opt/kafka/conf/certs -type f \\( -name '*.crt' -o -name '*.pem' \\) -print -exec openssl x509 -in {} -noout -dates -checkend 2592000 \\; ; ls -l /opt/kafka/conf/certs/*.p12 2>/dev/null", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "CRT/PEM 证书有效期超过 30 天且 PKCS12 文件存在 → OK；30 天内到期 → WARN；缺失或已过期 → CRIT"),
    _middleware_metric("local.kafka.system.parameters", "Kafka 系统参数", "su - kafka -c 'ulimit -n; ulimit -u'; free -h | grep Swap; cat /proc/sys/vm/swappiness", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "nofile≥65535、nproc≥4096、Swap 未使用、swappiness=0 → OK；参数不足或 Swap 使用 → WARN/CRIT"),
    _middleware_metric("local.zookeeper.node.health", "ZooKeeper 节点健康", "echo ruok | nc -w 3 127.0.0.1 2181; echo stat | nc -w 3 127.0.0.1 2181 | egrep 'Mode|Node count|Connections'; /opt/zookeeper/bin/zkServer.sh status /opt/zookeeper/conf/zoo.cfg", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "返回 imok 且 Mode 为 leader/follower；规划 3 节点为 1 leader + 2 follower；无响应、无 leader 或节点不足为 CRIT，leader 频繁切换为 WARN", unit="布尔"),
    _middleware_metric("local.zookeeper.ports.health", "ZooKeeper 核心端口", "ss -tlnp | grep -E ':2181|:2888|:3888'", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "clientPort、peerPort、electionPort 均 LISTEN → OK；缺少 1 个 → WARN；缺少 2 个及以上 → CRIT", unit="端口数"),
    _middleware_metric("local.zookeeper.error_log", "ZooKeeper 关键错误日志", "grep -R -iE 'ERROR|FATAL|OutOfMemory|NotLeader|IOException|Session expired' <ZOOKEEPER_LOG> 2>/dev/null | tail -30", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P0-TABLE5", "无持续 ERROR/FATAL/OOM/NotLeader/Session expired → OK；命中关键错误 → CRIT", unit="布尔"),
    _middleware_metric("local.zookeeper.mntr.health", "ZooKeeper 延迟与积压请求", "echo mntr | nc -w 3 127.0.0.1 2181 | egrep 'zk_avg_latency|zk_max_latency|zk_outstanding_requests|zk_num_alive_connections|zk_znode_count|zk_watch_count'", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "zk_max_latency ≤ 50ms 且 outstanding_requests=0 → OK；max latency 51–200ms 或存在积压 → WARN；>200ms → CRIT", unit="毫秒"),
    _middleware_metric("local.zookeeper.data.retention", "ZooKeeper 数据与日志留存", "du -sh <ZOOKEEPER_DATA> <ZOOKEEPER_DATALOG> 2>/dev/null; ls -lt <ZOOKEEPER_DATA>/version-2 2>/dev/null | head -10; ls -lt <ZOOKEEPER_DATALOG>/version-2 2>/dev/null | head -10", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "dataDir/dataLogDir 可读且 version-2 目录存在、增长受控 → OK；目录缺失或无法读取 → CRIT", unit="布尔"),
    _middleware_metric("local.zookeeper.config.baseline", "ZooKeeper 配置基线", "grep -E '^(dataDir|dataLogDir|clientPort|server\\.|autopurge|4lw.commands.whitelist|admin.enableServer|standaloneEnabled|reconfigEnabled)' <ZOOKEEPER_CONF>; cat <ZOOKEEPER_DATA>/myid", "Kafka+Zookeeper运维巡检手册v1.0.docx", "P1-TABLE6", "dataDir/dataLogDir/clientPort/server.*、autopurge 与 myid 可读取且符合集群规划 → OK；关键项缺失或 myid 不可读 → CRIT", unit="布尔"),

    _middleware_metric("local.mysql.service.health", "MySQL 服务健康", "pgrep -fa 'mysqld.*defaults-file=/opt/mysql/conf/my.cnf'; ss -tlnp | grep ':3306'", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "mysqld 进程存在且 3306 LISTEN → OK；任一缺失 → CRIT"),
    _middleware_metric("local.mysql.login.version", "MySQL 登录与版本", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SELECT @@version,@@hostname,@@port;\"", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "可认证登录且版本为 MySQL 8.0.44、端口为 3306 → OK；登录失败或版本/端口偏离 → CRIT"),
    _middleware_metric("local.mysql.role.gtid", "MySQL 角色与 GTID", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SELECT @@server_id,@@gtid_mode,@@enforce_gtid_consistency,@@read_only,@@super_read_only;\"", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "server_id 符合节点规划、GTID/一致性 ON，主库可写、从库只读 → OK；偏离 → CRIT"),
    _middleware_metric("local.mysql.replica.threads", "MySQL 复制线程", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW REPLICA STATUS\\G\" | egrep 'Source_Host|Replica_IO_Running|Replica_SQL_Running|Last_IO_Errno|Last_SQL_Errno'", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "Replica_IO_Running=Yes、Replica_SQL_Running=Yes 且错误码为 0 → OK；线程停止或有错误 → CRIT"),
    _middleware_metric("local.mysql.replication.lag", "MySQL 复制延迟", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW REPLICA STATUS\\G\" | egrep 'Seconds_Behind_Source|Read_Source_Log_Pos|Exec_Source_Log_Pos|Retrieved_Gtid_Set|Executed_Gtid_Set'", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "Seconds_Behind_Source≤30 且 Read/Exec 位置推进 → OK/WARN；NULL、位置不推进或持续超过 30 秒 → CRIT"),
    _middleware_metric("local.mysql.connection.pressure", "MySQL 连接压力", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW GLOBAL STATUS LIKE 'Threads_connected'; SHOW GLOBAL STATUS LIKE 'Max_used_connections'; SHOW VARIABLES LIKE 'max_connections';\"", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "Max_used_connections/max_connections≤80% → OK；80%–95% → WARN；>95% → CRIT"),
    _middleware_metric("local.mysql.binlog.relaylog", "MySQL Binlog/Relay Log 状态", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW MASTER STATUS\\G; SHOW BINARY LOGS;\"; ls -lh /opt/mysql/binlog | tail -10; ls -lh /opt/mysql/relaylog 2>/dev/null | tail -10", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "Binlog 正常生成、从库 Relay Log 可读且目录存在 → OK；缺失或不可读 → CRIT"),
    _middleware_metric("local.mysql.error_log.key_evidence", "MySQL 关键错误日志", "grep -iE 'ERROR|FATAL|crash|corrupt|Out of memory|Disk is full|Too many connections|Access denied|Aborted connection' /opt/mysql/logs/error.log 2>/dev/null | tail -50", "Mysql运维巡检手册v1.0.docx", "P0-TABLE5", "无持续关键错误 → OK；命中关键错误 1–10 条 → WARN；超过 10 条或出现崩溃/OOM/损坏 → CRIT"),
    _middleware_metric("local.mysql.slow_query.key_evidence", "MySQL 慢 SQL", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW VARIABLES LIKE 'slow_query_log'; SHOW VARIABLES LIKE 'long_query_time'; SHOW GLOBAL STATUS LIKE 'Slow_queries';\"; tail -100 /opt/mysql/logs/slow.log 2>/dev/null", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "slow_query_log=ON、long_query_time=1 且慢查询增长受控 → OK；异常突增 → WARN/CRIT"),
    _middleware_metric("local.mysql.innodb.waits", "MySQL InnoDB 长事务与锁等待", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SELECT COUNT(*) AS long_trx FROM information_schema.innodb_trx WHERE TIME_TO_SEC(TIMEDIFF(NOW(),trx_started))>300; SHOW ENGINE INNODB STATUS\\G\" | egrep -i 'long_trx|LATEST DETECTED DEADLOCK|history list length|row lock|TRANSACTIONS' | head -50", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "无超过 300 秒长事务、死锁和异常锁等待 → OK；少量等待 → WARN；持续长事务/死锁 → CRIT"),
    _middleware_metric("local.mysql.buffer_pool.hit_ratio", "MySQL Buffer Pool 命中率", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW GLOBAL STATUS WHERE Variable_name IN ('Innodb_buffer_pool_read_requests','Innodb_buffer_pool_reads'); SHOW VARIABLES LIKE 'innodb_buffer_pool_size';\"", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "Buffer Pool 命中率≥99% → OK；95%–99% → WARN；<95% → CRIT；Buffer Pool 大小符合基线 → OK"),
    _middleware_metric("local.mysql.sql.digest", "MySQL SQL 摘要", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SHOW GLOBAL STATUS WHERE Variable_name IN ('Threads_running','Questions','Created_tmp_disk_tables','Handler_read_rnd_next','Select_full_join');\"", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "Threads_running 无持续堆积且全表扫描/磁盘临时表无异常突增 → OK；持续升高 → WARN/CRIT"),
    _middleware_metric("local.mysql.config.baseline", "MySQL 配置基线", "grep -E '^(bind-address|server_id|report_host|port|datadir|socket|log_error|slow_query_log|long_query_time|log_bin|gtid_mode|enforce_gtid_consistency|binlog_format|sync_binlog|relay_log|relay_log_recovery|read_only|super_read_only|innodb_buffer_pool_size|innodb_flush_log_at_trx_commit|max_connections)' /opt/mysql/conf/my.cnf", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "配置与节点角色、GTID、Binlog、日志、InnoDB 持久化和连接上限基线一致 → OK；关键项偏离 → CRIT"),
    _middleware_metric("local.mysql.security.accounts", "MySQL 用户与安全配置", "/opt/mysql/bin/mysql --socket=/opt/mysql/tmp/mysql.sock -uroot -p -e \"SELECT user,host,account_locked,password_expired FROM mysql.user ORDER BY user,host; SHOW VARIABLES WHERE Variable_name IN ('local_infile','skip_name_resolve','secure_file_priv','mysqlx');\"", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "无异常高权限账号，local_infile=OFF、skip_name_resolve=ON、secure_file_priv 受限、mysqlx=OFF → OK；偏离 → CRIT"),
    _middleware_metric("local.mysql.backup.status", "MySQL 备份状态", "MYSQL_BACKUP_DIR=/opt/mysql/backuptest -d \"$MYSQL_BACKUP_DIR\" && find \"$MYSQL_BACKUP_DIR\" -type f -mtime -2 -ls | tail -20 || echo '未发现本地备份目录'", "Mysql运维巡检手册v1.0.docx", "P1-TABLE6", "可读取到最近 2 天有效备份文件 → OK；无备份、失败或文件异常 → CRIT"),

    _middleware_metric("local.nacos.service.health", "Nacos 服务健康", "pgrep -fa 'com.alibaba.nacos|nacos.home|/opt/nacos'", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "服务 active、进程存在且启动路径符合 /opt/nacos → OK；否则 → CRIT"),
    _middleware_metric("local.nacos.core_ports.health", "Nacos 核心端口", "ss -tlnp | egrep ':8848|:9848|:9849|:7848'", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "按部署模式规划端口均 LISTEN → OK；API/gRPC/JRaft 关键端口缺失 → CRIT"),
    _middleware_metric("local.nacos.http.health", "Nacos HTTP 健康", "curl -sS --connect-timeout 3 http://127.0.0.1:8848/nacos/actuator/health", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "返回 UP 或 HTTP 200 → OK；超时、拒绝连接、5xx 或非 UP → CRIT"),
    _middleware_metric("local.nacos.cluster.config", "Nacos 集群节点配置", "cat /opt/nacos/conf/cluster.conf; grep -E '^nacos.server.ip=' /opt/nacos/conf/application.properties", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "cluster.conf 包含规划节点与端口，本机 nacos.server.ip 与实际业务 IP 一致 → OK；节点缺失或 IP 错误 → CRIT"),
    _middleware_metric("local.nacos.cluster.nodes", "Nacos 集群节点", "curl -sS 'http://127.0.0.1:8848/nacos/v2/core/cluster/node/list?accessToken=<TOKEN>'", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "规划节点全部在线且 alive=true → OK；节点缺失或可用节点少于 2 → CRIT"),
    _middleware_metric("local.nacos.mysql.connectivity", "Nacos MySQL 连接", "grep -E '^(spring.sql.init.platform|db.num|db.url.0|db.user.0)' /opt/nacos/conf/application.properties; nc -vz <MYSQL_HOST> 3306", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "MySQL 平台、库地址和 3306 可达且符合基线 → OK；否则 → CRIT"),
    _middleware_metric("local.nacos.error_log", "Nacos 错误日志", "grep -R -iE 'ERROR|FATAL|OutOfMemory|No DataSource|SQLException|Connection refused|raft|failed' /opt/nacos/logs | tail -80", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "无持续 OOM、数据库连接失败或 JRaft 失败 → OK；可解释短时异常 → WARN；持续关键错误 → CRIT"),
    _middleware_metric("local.nacos.auth.config", "Nacos 认证与节点身份", "grep -E '^(nacos.core.auth.enabled|nacos.core.auth.system.type|nacos.core.auth.server.identity.key|nacos.core.auth.server.identity.value|nacos.core.auth.plugin.nacos.token.secret.key)' /opt/nacos/conf/application.properties", "Nacos运维巡检手册v1.0.docx", "P0-TABLE5", "认证开启、system.type=nacos、节点身份和 token 密钥非空且集群一致 → OK；认证关闭或关键项为空 → CRIT"),
    _middleware_metric("local.nacos.http.errors", "Nacos 接口延迟与 5xx", "tail -n 100 /opt/nacos/logs/access_log.* 2>/dev/null; grep -R ' 5[0-9][0-9] ' /opt/nacos/logs/access_log.* 2>/dev/null | tail -50", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "访问日志无持续 5xx 且接口耗时无持续升高 → OK；5xx 或耗时异常 → WARN/CRIT"),
    _middleware_metric("local.nacos.jvm.parameters", "Nacos JVM 与启动参数", "grep -E 'JAVA_HOME|NACOS_HOME|JAVA_OPT|Xms|Xmx|Xmn|server.port' /home/nacos/.bash_profile /opt/nacos/bin/startup.sh /opt/nacos/conf/application.properties 2>/dev/null", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "JAVA_HOME、NACOS_HOME=/opt/nacos、JVM 内存参数和 server.port=8848 与部署基线一致 → OK；偏离 → CRIT"),
    _middleware_metric("local.nacos.thread.fd.pressure", "Nacos 线程与文件句柄", "PID=$(pgrep -f 'com.alibaba.nacos|nacos.home|/opt/nacos' | head -1); test -n \"$PID\" && grep -E 'Threads|FDSize' /proc/$PID/status; test -n \"$PID\" && ls /proc/$PID/fd | wc -l; su - nacos -c 'ulimit -n; ulimit -u'", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "线程和文件句柄无持续增长，nofile>=65535 且 nproc 符合主机规范 → OK；资源逼近上限 → WARN/CRIT"),
    _middleware_metric("local.nacos.config.baseline", "Nacos 配置基线", "grep -E '^(nacos.server.ip|spring.sql.init.platform|db.num|db.url.0|db.user.0|db.pool.config|server.tomcat.accesslog.enabled|nacos.istio.mcp.server.enabled)' /opt/nacos/conf/application.properties; cat /opt/nacos/conf/cluster.conf", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "本机 IP、外置 MySQL、连接池、Access Log、cluster.conf 与部署规范一致 → OK；配置漂移 → CRIT"),
    _middleware_metric("local.nacos.log.data.retention", "Nacos 日志与数据目录留存", "du -sh /opt/nacos/logs /opt/nacos/data 2>/dev/null; find /opt/nacos/logs -type f -mtime +30 -ls 2>/dev/null | head -50", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "日志和数据目录增长平稳，无大量历史日志长期堆积 → OK；目录容量或留存异常 → WARN/CRIT"),
    _middleware_metric("local.nacos.metrics.collection", "Nacos 监控指标采集", "curl -sS --connect-timeout 3 http://127.0.0.1:8848/nacos/actuator/prometheus | egrep 'jvm_memory|system_cpu|nacos' | head -50", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "Prometheus 接口可访问并返回 JVM、CPU、Nacos 指标 → OK；接口不可用或无有效指标 → CRIT"),
    _middleware_metric("local.nacos.database.errors", "Nacos 数据库错误趋势", "grep -R -iE 'SQLException|Communications link failure|Access denied|connectionTimeout|No DataSource|HikariPool' /opt/nacos/logs 2>/dev/null | tail -80", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "无持续数据库连接失败、认证失败、连接池耗尽或 SQL 异常 → OK；持续出现 → WARN/CRIT"),
    _middleware_metric("local.nacos.system.parameters", "Nacos 系统时间与安全参数", "timedatectl; cat /proc/sys/vm/swappiness; su - nacos -c 'umask; ulimit -n; ulimit -u'", "Nacos运维巡检手册v1.0.docx", "P1-TABLE6", "系统时间同步、Swap 策略、umask、nofile 和 nproc 符合主机规范 → OK；参数不足或 Swap 使用 → WARN/CRIT"),

    _middleware_metric("local.rabbitmq.service.health", "RabbitMQ 服务健康", "pgrep -fa 'beam.smp|rabbitmq-server'; systemctl is-active rabbitmq", "Rabbitmq运维巡检手册v1.0.docx", "P0-TABLE5", "systemd active 且 beam.smp/rabbitmq-server 存在 → OK；否则 → CRIT"),
    _middleware_metric("local.rabbitmq.node.health", "RabbitMQ 节点健康", "rabbitmq-diagnostics ping; rabbitmq-diagnostics status", "Rabbitmq运维巡检手册v1.0.docx", "P0-TABLE5", "Ping succeeded 且可返回节点/版本/运行时信息 → OK；失败或超时 → CRIT"),
    _middleware_metric("local.rabbitmq.cluster.nodes", "RabbitMQ 集群节点", "rabbitmqctl cluster_status", "Rabbitmq运维巡检手册v1.0.docx", "P0-TABLE5", "running_nodes 包含规划 3 节点 → OK；少于 3 → WARN；少于 2 → CRIT"),
    _middleware_metric("local.rabbitmq.alarm.partition", "RabbitMQ 告警与分区", "rabbitmq-diagnostics check_local_alarms; rabbitmqctl cluster_status | egrep -i 'alarms|partitions|running_nodes'", "Rabbitmq运维巡检手册v1.0.docx", "P0-TABLE5", "无 memory/disk alarm 且 partitions 为空 → OK；出现告警或网络分区 → CRIT"),
    _middleware_metric("local.rabbitmq.queue.backlog", "RabbitMQ 队列积压", "rabbitmqctl list_queues -p / name state messages messages_ready messages_unacknowledged consumers", "Rabbitmq运维巡检手册v1.0.docx", "P0-TABLE5", "队列 running 且消息量不持续增长 → OK；积压达到产品补充阈值 → WARN/CRIT"),
    _middleware_metric("local.rabbitmq.connection.pressure", "RabbitMQ 连接与信道压力", "rabbitmqctl list_connections state channels send_pend; rabbitmqctl list_channels messages_unacknowledged", "Rabbitmq运维巡检手册v1.0.docx", "P1-TABLE6", "无 blocked/closing/flow 且 send_pend 不堆积 → OK；达到产品补充阈值 → WARN/CRIT"),

    _middleware_metric("local.redis.service.health", "Redis 服务健康", "pgrep -fa 'redis-server.*(6379|16379|7000)'; systemctl is-active redis", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "systemd active 且 redis-server 使用规划配置 → OK；否则 → CRIT"),
    _middleware_metric("local.redis.ping.version", "Redis PING 与版本", "redis-cli -h 127.0.0.1 -p <PORT> PING; redis-cli -h 127.0.0.1 -p <PORT> INFO server", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "返回 PONG 且版本/端口符合模式 → OK；认证失败、拒绝连接或超时 → CRIT"),
    _middleware_metric("local.redis.replication.health", "Redis 复制健康", "redis-cli -p <PORT> INFO replication", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "角色、从库数和 master_link_status=up 符合规划 → OK；不符合 → CRIT"),
    _middleware_metric("local.redis.sentinel.health", "Redis Sentinel 健康", "redis-cli -p 26379 INFO sentinel; redis-cli -p 26379 SENTINEL masters", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "1 master、2 slave、2 其他 Sentinel 且无 s_down/o_down/disconnected → OK；否则 → CRIT"),
    _middleware_metric("local.redis.cluster.health", "Redis Cluster 健康", "redis-cli -p 7000 CLUSTER INFO; redis-cli -p 7000 CLUSTER NODES", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "cluster_state=ok、16384/16384 slots、3 master+3 slave 且无 fail/noaddr → OK；否则 → CRIT"),
    _middleware_metric("local.redis.persistence.health", "Redis 持久化健康", "redis-cli -p <PORT> INFO persistence; redis-cli -p <PORT> CONFIG GET appendonly appendfsync dir", "Redis运维巡检手册v1.0.docx", "P0-TABLE5", "loading=0、RDB/AOF 状态正常且 appendfsync=everysec → OK；异常 → CRIT"),

    _middleware_metric("local.rocketmq.namesrv.health", "RocketMQ NameServer 健康", "pgrep -fa 'NamesrvStartup|mqnamesrv'; tail -n 50 /opt/rocketmq/logs/rocketmqlogs/namesrv.log", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "进程存在且日志显示启动成功 → OK；inactive/failed 或启动失败 → CRIT"),
    _middleware_metric("local.rocketmq.broker.health", "RocketMQ Broker 健康", "pgrep -fa 'BrokerStartup|mqbroker'; tail -n 50 /opt/rocketmq/logs/rocketmqlogs/broker.log", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "Broker 进程存在、配置正确且无持续 ERROR/FATAL → OK；否则 → CRIT"),
    _middleware_metric("local.rocketmq.core_ports.health", "RocketMQ 核心端口", "ss -tlnp | egrep ':9876|:9877|:10911|:10912'", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "按模式检查 9876/9877/10911/10912 均 LISTEN → OK；关键端口缺失 → CRIT"),
    _middleware_metric("local.rocketmq.cluster.registration", "RocketMQ 集群注册", "mqadmin clusterList -n <NAMESRV_ADDR>", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "返回预期集群、Broker、副本和 Master BrokerId=0 → OK；Broker 缺失或副本不足 → WARN/CRIT"),
    _middleware_metric("local.rocketmq.controller.sync_set", "RocketMQ Controller 同步集合", "mqadmin getControllerMetaData -a <CONTROLLER_ADDR>; mqadmin getSyncStateSet -a <CONTROLLER_ADDR> -b <BROKER>", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "有 leader、3 Controller 且 SyncStateSet 至少 2 副本 → OK；无 leader/少于多数派 → CRIT"),
    _middleware_metric("local.rocketmq.consumer.lag", "RocketMQ 消费堆积", "mqadmin consumerProgress -n <NAMESRV_ADDR>; mqadmin statsAll -n <NAMESRV_ADDR>", "Rocketmq运维巡检手册v1.0.docx", "P0-TABLE5", "消费 diff/lag 为 0 或在业务可接受范围且不持续增长 → OK；快速增长 → WARN/CRIT"),

    _middleware_metric("local.tomcat.service.health", "Tomcat 服务健康", "ps -ef | grep '[o]rg.apache.catalina.startup.Bootstrap'", "Tomcat运维巡检手册v1.0.docx", "P0-TABLE5", "Tomcat 进程存在且服务 active → OK；否则 → CRIT"),
    _middleware_metric("local.tomcat.http.health", "Tomcat HTTP 健康", "ss -lntp | egrep '(:8080|:8443|:8005)\\b'", "Tomcat运维巡检手册v1.0.docx", "P0-TABLE5", "HTTP 端口处于 LISTEN 且归属 Tomcat Java 进程 → OK；未监听或端口冲突 → CRIT"),
    _middleware_metric("local.tomcat.access_log.errors", "Tomcat 访问与错误日志", "tail -200 /opt/tomcat/logs/catalina.out | egrep -i 'Server startup in|SEVERE|Exception|OutOfMemoryError|Address already in use'", "Tomcat运维巡检手册v1.0.docx", "P0-TABLE5", "启动成功且无持续 SEVERE/OOM/端口占用等关键错误 → OK；关键错误 → CRIT"),
    _middleware_metric("local.tomcat.jvm.memory", "Tomcat JVM 内存", "PID=$(pgrep -f 'org.apache.catalina.startup.Bootstrap' | head -1); ps -o pid,rss,vsz,%mem,etime,cmd -p \"$PID\"; free -h", "Tomcat运维巡检手册v1.0.docx", "P0-TABLE5", "RSS/JVM 配置与业务负载匹配且 available 内存充足、swap 未持续使用 → OK；内存压力或 OOM 风险 → WARN/CRIT"),
    _middleware_metric("local.tomcat.thread_pool.pressure", "Tomcat 文件句柄与线程压力", "PID=$(pgrep -f 'org.apache.catalina.startup.Bootstrap' | head -1); echo fd=$(ls /proc/$PID/fd 2>/dev/null | wc -l); echo threads=$(ls /proc/$PID/task 2>/dev/null | wc -l); cat /proc/$PID/limits 2>/dev/null | egrep 'Max open files|Max processes'", "Tomcat运维巡检手册v1.0.docx", "P0-TABLE5", "文件句柄/线程数接近限制但未耗尽，且无 too many open files 或线程堆积 → OK；接近/超过限制 → WARN/CRIT"),
    _middleware_metric("local.tomcat.security.baseline", "Tomcat 安全配置基线", "egrep -n '(<Server port=|<Connector|autoDeploy=|deployOnStartup=|server=)' /opt/tomcat/conf/server.xml", "Tomcat运维巡检手册v1.0.docx", "Tomcat-P1", "Connector/Server 端口符合规划，autoDeploy/deployOnStartup 按基线关闭且 Server 响应头受控 → OK；偏离 → WARN/CRIT"),
]

METRICS.extend(_ADDITIONAL_MIDDLEWARE_METRICS)

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
    """返回已注册指标总数。"""
    return len(METRICS)
