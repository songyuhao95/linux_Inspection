# Keepalived 中间件监控（keepalived-p0-v1）

## 范围

Keepalived 模块依据《安徽农金Nginx、Keepalived运维巡检手册v1.0.docx》的
Keepalived P0/P1 检查项实现。模块文件为 `inspect/modules/keepalived.py`，阈值基线为
`inspect/data/thresholds/keepalived-p0-v1.yaml`。采集是只读的；健康检查脚本只检查
文件存在性和权限，不执行配置中的任意脚本。

## 指标清单（8 个）

| metric_id | 名称 | 取值与判定 | 文档来源 |
| --- | --- | --- | --- |
| `local.keepalived.process.present` | Keepalived 进程存在性 | `pgrep -fa '(^|[[:space:]/])keepalived[[:space:]]'`；白名单主机未运行为 CRIT，非白名单主机跳过模块 | P0「Keepalived本节点服务」 |
| `local.keepalived.version` | Keepalived 版本 | 从运行进程命令行解析实际二进制执行 `-v`，与 `keepalived_version` 精确比较 | 部署规范版本要求 |
| `local.keepalived.vip.bound` | VIP 绑定状态 | 从实际配置解析 `state` 和 `virtual_ipaddress`，再用 `ip -brief addr` 检查 VIP | P0「VIP绑定状态」 |
| `local.keepalived.vip.access` | VIP 访问 | 从实际配置读取 VIP 用于绑定核对；仅在目标主机执行 `curl -I http://127.0.0.1:keepalived_port/` 检查本机 HTTP | P0「VIP访问」 |
| `local.keepalived.config.baseline` | 配置基线 | 检查 `state`、`interface`、`virtual_router_id`、`priority`、`advert_int`、`virtual_ipaddress`、`script`、`track_script` | P0「Keepalived配置基线」 |
| `local.keepalived.healthcheck.script` | 健康检查脚本 | 从实际配置解析 `script` 路径，检查脚本存在且可执行；不执行脚本 | P0「健康检查脚本」 |
| `local.keepalived.error_log.key_evidence` | 关键日志证据 | 读取末尾 1000 行，统计 MASTER/BACKUP/FAULT、VRRP、脚本失败等证据 | P0「关键日志」 |
| `local.keepalived.capability.stability` | 能力与漂移稳定性 | 检查二进制 capabilities、systemd capability 配置和日志漂移/故障证据 | P1「Keepalived能力与漂移稳定性」 |

## 进程发现、路径发现与跳过规则

1. 先用 `pgrep -fa '(^|[[:space:]/])keepalived[[:space:]]'` 发现运行实例；从进程命令行提取二进制路径和 `-f`
   指定的配置路径。
2. 路径未从进程/配置识别时，依次使用 `inspect.conf` 的 `keepalived_bin`、
   `keepalived_conf`、`keepalived_log`、`keepalived_vip`、`keepalived_port` 候选值兜底。
3. 进程未运行且主机 IP 不在 `keepalived_whitelist` 时，丢弃全部 Keepalived 指标，
   不把普通 Linux 主机误报为 Keepalived 主机；白名单主机只保留进程指标并判定 CRIT。
   进程发现本身技术失败时保留指标并报告 UNKNOWN。
4. 进程运行但实际路径和候选值都不可用时，相关指标为 UNKNOWN，不按文档中的固定路径
   默认通过。

当前 v1 按主机的一组逻辑实例生成结果。若主机存在多个 master 进程，当前取第一条匹配
进程，因此不会伪造“全部实例均正常”的结论。后续可参考 Nginx 多实例方案增加带
`instance_id`、PID、配置、VIP、端口和日志路径的实例列表，按“主机 → 实例 → 指标”展开。

## inspect.conf 配置

格式为 `参数 = 候选值1|候选值2|...`，示例 IP 为 TEST-NET 脱敏地址：

```ini
keepalived_bin = /usr/sbin/keepalived|/usr/local/sbin/keepalived|/opt/keepalived/sbin/keepalived
keepalived_conf = /opt/keepalived/conf/keepalived.conf|/etc/keepalived/keepalived.conf|/usr/local/etc/keepalived/keepalived.conf
keepalived_log = /opt/keepalived/logs/keepalived.log|/var/log/keepalived.log
keepalived_vip = 192.0.2.253
keepalived_port = 8010
keepalived_version = keepalived/2.2.8
keepalived_baseline = state=True|interface=True|virtual_router_id=True|priority=True|advert_int=True|virtual_ipaddress=True|script=True|track_script=True
keepalived_whitelist = 192.0.2.10|192.0.2.11
```

SSH 账号、密码和连接参数继续只放在私有 `inventory/hosts.local.ini` / `hosts.ini`，不放入
`inspect.conf`；该文件应保持 700 权限。

## 判定与复现

- **进程/版本**：只从运行进程的实际二进制取版本；`keepalived/x.y.z` 与配置基线一致为
  OK，不一致为 CRIT；没有运行进程、版本输出或版本基线为 UNKNOWN。
- **VIP 绑定**：`state=MASTER` 且 VIP 出现在本机 `ip -brief addr` 为 OK；`BACKUP` 且
  本机没有 VIP 为 OK；其他组合为 CRIT，避免双 MASTER 或 MASTER 无 VIP 被判正常。
- **VIP 访问**：VIP 地址来自运行配置并用于绑定核对，端口来自配置或
  `keepalived_port` 兜底；为避免巡检产生跨主机访问，HTTP 只在目标主机本机执行
  `curl http://127.0.0.1:端口/`。未发现 VIP/端口、连接失败或 HTTP 5xx 为 CRIT。
- **配置基线**：逐项检查 8 个关键指令，缺少指令为 WARN，配置路径不存在或不可读为
  UNKNOWN；不是只检查文件是否存在。
- **健康脚本**：解析 `vrrp_script` 的 `script` 路径，检查文件存在、普通文件和执行权限。
  不执行脚本，因此不会把未执行伪装成返回码 0。
- **日志**：关键命中表示末尾 1000 行出现证据；FAULT、脚本失败为 CRIT，多次 MASTER/
  BACKUP 漂移为 WARN，日志不可发现为 UNKNOWN。
- **能力稳定性**：同时观察 `getcap`、systemd capability 字段和日志；能力缺失或故障
  证据为 CRIT，日志缺失为 UNKNOWN，漂移次数较多为 WARN。

每个指标的 `command` 会写入 JSON、Excel 和 HTML，动态路径还会输出
`INSPECT_KEEPALIVED_*` 标记，便于确认实际使用的是进程发现路径还是 `inspect.conf` 兜底路径。

## 报表与 CLI

- Excel `Local` 只保留 Linux 基础指标；新增 `keepalived` Sheet 只列
  `local.keepalived.*` 指标。
- HTML 按 `local.keepalived.` 前缀归入 Keepalived 中间件，支持主机、状态、中间件、
  监控指标多选筛选和分组。
- 默认执行 `linux_basic` 加全部已注册中间件；`--keepalived` 只执行 Keepalived（仍保留
  Linux 基础指标），`--nginx` 与其互斥。

```bash
bash inspect.sh --local --keepalived
bash inspect.sh -H inspection --keepalived --excel out/keepalived.xlsx --html out/keepalived.html
```
