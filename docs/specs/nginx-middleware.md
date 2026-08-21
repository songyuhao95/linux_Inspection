# Nginx 中间件监控（nginx-p0-v1）

## 范围

Nginx 中间件模块是第一个中间件适配器，指标按《安徽农金Nginx、Keepalived运维
巡检手册v1.0.docx》（Nginx 手册 sha256[:8]=72b0834d）P0/P1 指标表转写。
模块文件：`inspect/modules/nginx.py`；阈值基线：`inspect/data/thresholds/nginx-p0-v1.yaml`。

## 指标清单（9 个）

| metric_id | 名称 | 命令 | 文档来源 |
| --- | --- | --- | --- |
| `local.nginx.process.present` | Nginx 进程存在性 | `pgrep -fa '[n]ginx: (master|worker) process'`（`[n]` 防止 shell 自匹配） | P0「Nginx本节点服务」 |
| `local.nginx.version` | Nginx 版本 | 从运行中的 master 进程解析可执行文件，执行 `nginx -v`；与 `inspect.conf` 的 `nginx_version` 比较 | P0「Nginx版本」 |
| `local.nginx.config.valid` | 配置有效性 | 自动从 master 进程解析 `-c/-e`，无可用值时按 `inspect.conf` 候选，执行 `nginx -t` | P0「Nginx配置有效性」 |
| `local.nginx.port.listening` | 端口监听与本地访问 | 从实际配置 `listen` 指令提取端口；无端口时使用 `inspect.conf` 的 `nginx_port`，再执行 `ss` + `curl` | P0「Nginx端口与本地访问」 |
| `local.nginx.error_log.key_evidence` | 关键日志 | 从进程/配置解析 `error_log`，无可用值时按 `inspect.conf` 候选，读取末尾 1000 行 | P0「关键日志」 |
| `local.nginx.connections.status` | 连接状态（stub_status） | 对实际 `listen` 端口（或 `inspect.conf` 候选）访问 `/nginx_status` | P1「Nginx连接状态」 |
| `local.nginx.access_log.status_codes` | 访问日志状态码 | 从 `nginx -T` 解析 `access_log`，无可用值时按 `inspect.conf` 候选，读取末尾 1000 行 | P1「访问日志状态码」 |
| `local.nginx.config.baseline` | 配置基线 | 自动解析配置文件后 grep `worker_processes` 等核心/关注指令 | P1「Nginx配置基线」 |
| `local.nginx.security.baseline` | 安全配置基线 | 自动解析配置文件后 grep `server_tokens`、`autoindex` 等安全指令 | P1「安全配置基线」 |

命令由 `inspect/ansible_runner.py` 固定生成。为把进程/配置发现结果传递给后续只读检查，
Nginx 内部命令允许固定生成的 shell 变量；候选路径先经过安全字符集校验，用户配置不能
直接注入任意命令。HTTP 探测使用 `curl`（手册要求），仅限 `local.nginx.*` 指标模板。

## 进程发现与白名单

默认巡检先执行 `local.nginx.process.present`（进程发现）：

- **运行中**：采集全部 9 个 Nginx 指标；
- **未运行且不在白名单**：丢弃该主机全部 Nginx 指标（该主机不是 Nginx 节点，跳过）；
- **未运行且在白名单**：只保留 `local.nginx.process.present`，判定 **CRIT 未运行**
  （normalize 复用进程存在性判定：absent → CRIT）；
- **进程发现采集失败**（无权限等）：保留全部 Nginx 指标为 UNKNOWN+error（不伪装结论）。

白名单来自仓库根 `inspect.conf` 的 `nginx_whitelist` 候选列表；
选择逻辑实现为 `ansible_runner.select_nginx_metrics`，在 local 与 Ansible 两条执行
路径的结果组装阶段统一应用，host-result-v1 的 `host.product_profiles` 据此标记 `nginx`。

## 配置（inspect.conf）

格式为 `参数 = 候选值1|候选值2|...`，当前字段：`nginx_bin`、`nginx_conf`、
`nginx_error_log`、`nginx_access_log`、`nginx_port`、`nginx_baseline`、
`nginx_version`、`nginx_whitelist`。实际路径取值优先级为：运行中的 master 进程参数 → `nginx -T`/实际
配置 → `inspect.conf` 候选。两处都没有可用路径时，相关指标为 UNKNOWN；不会再把
文档中的固定路径当作隐式现场事实。inspect.conf 在 Linux 首次读取时设为 700。
Ansible 账号、密码和连接参数继续只放在 `inventory/hosts.local.ini` 或
`inventory/hosts.ini`，不放入 inspect.conf。

## 阈值判定说明

报告中的 `threshold_rule` 现在把“检查对象、取值来源和判定动作”写在一起，便于
运维复现：

- **配置有效性**：执行 `nginx_bin -t -e nginx_error_log -c nginx_conf`，把错误日志
  路径显式指定为配置中的日志文件，避免测试账号因默认 `/var/log/nginx/error.log`
  无权限而无法完成配置测试。Nginx 的成功信息通常写到 stderr，因此 stdout 和 stderr
  都会检查；同时出现 `syntax is ok` 与 `test is successful` 才是 OK。
- **版本**：先从运行中的 `nginx: master process` 命令行取得实际二进制，再执行该二进制
  的 `nginx -v`；版本输出中的 `nginx/x.y.z` 与 `inspect.conf` 的 `nginx_version` 候选值
  逐一精确比较。一致为 OK，不一致为 CRIT；没有运行中的 master、没有版本输出或没有
  配置版本基线为 UNKNOWN。不会因为候选路径下存在一个未运行的 Nginx 二进制而判定版本正常。
- **端口监听与本地访问**：先从实际 Nginx 配置的 `listen 地址:端口` 提取监听地址和端口；
  无法提取完整监听地址时不伪造访问结论，使用 `INSPECT_NGINX_PORT_NOT_FOUND` → UNKNOWN。
  逐端口用 `ss -tlnp` 检查 LISTEN，再在目标主机使用配置监听地址 curl 访问；连接失败、
  未监听或 HTTP 5xx 为 CRIT。
- **错误日志**：先从 master 的 `-e` 和配置文件的 `error_log` 解析，最后使用
  inspect.conf 的 `nginx_error_log` 候选；读取末尾 1000 行，扫描 emerg、alert、crit、
  error、permission denied、bind()、connect() failed、upstream timed out 等关键字；
  命中为 WARN，路径完全找不到为 UNKNOWN。
- **访问日志**：先从 `nginx -T` 的 `access_log` 解析，最后使用 inspect.conf 的
  `nginx_access_log` 候选；读取末尾 1000 行并逐行统计状态码，`normalized_value` 是
  5xx 命中行数，不是命令原始输出行数；5xx 命中为 WARN，路径完全找不到为 UNKNOWN。
- **配置基线**：文件来自自动发现的 `nginx_conf`，找不到时使用 inspect.conf 候选；检查
  `worker_processes`、`worker_connections`、`keepalive_timeout` 三项核心指令，
  同时采集 `worker_rlimit_nofile`、`use epoll`、`multi_accept`、
  `client_max_body_size`、`limit_req`、`limit_conn` 关注项。
- **安全基线**：同一自动发现的配置文件检查 inspect.conf `nginx_baseline` 指定的
  安全项（默认 `server_tokens_off=True`、`autoindex_off=True`），分别用于避免暴露
  版本信息和目录索引；缺任一项为 WARN。

## 多实例行为与演进方案

当前 `nginx-p0-v1` 的粒度是“每台主机一个逻辑 Nginx 实例”：

- 进程发现会匹配主机上的 Nginx master/worker 进程；只要发现任一匹配进程，主机就
  进入运行态。
- 配置、端口、日志和基线指标优先使用每个 master 进程/实际配置发现的一组路径，
  找不到时才使用 `inspect.conf` 中的
  `nginx_bin/nginx_conf/nginx_port/nginx_error_log/nginx_access_log`。因此同一主机有
  多个实例时，v1 不能逐实例给出结论，默认配置对应的实例是报告对象；进程存在性
  只能回答“是否有 Nginx 进程”，不能回答每个实例是否正常。
- 这不会把多个实例的输出静默拼成一个假值；但运维应把当前结果理解为“配置所指向
  实例的结果”，并在现场为目标实例填写配置文件、端口和日志路径。

可行的 v2 方案是把配置改为 `instances` 列表，每个实例至少包含：
`instance_id`、`nginx_bin`、`nginx_conf`、`nginx_port`、日志路径，以及可选的
`master_pid` 或 `process_pattern`。采集器对每个实例独立执行进程、配置、端口和日志
检查，事实源在 `evidence.details` 增加 `instance_id`、配置路径和端口，报表按
“主机 → 实例 → 指标”展示并支持实例筛选。PID 只作为当前采集时的身份校验，不能单独
作为长期标识；长期标识应使用人工配置的 `instance_id`，这样 master 重启后仍能追踪
同一个实例。该方案需要升级事实源契约/筛选维度后再实现，避免在 v1 的 metric_id
中拼接动态 PID。

## 报表集成

- **Excel**：`Local` 只列 Linux 基础指标；新增 `nginx` Sheet（`SHEET_NGINX`）只列
  `local.nginx.*` 指标，字段与 Local 一致；Sheet 顺序 Overview / Local / nginx /
  Errors-Evidence。
- **HTML**：`render_html._middleware_values` 按 metric_id 前缀 `local.nginx.` 归入
  「nginx」中间件维度；左侧中间件/监控指标多选筛选与按中间件/按监控指标分组自动生效；
  Linux 基础指标仍归「Linux 基础」。

## CLI

- 默认（无 `--nginx`）：`linux_basic` + 全部已注册中间件（当前 `nginx`）；
- `--nginx`：只巡检 Nginx 中间件（仍保留 Linux 主机基础指标）；
- 未来新增中间件时，`middleware_module_ids()` 自动纳入默认巡检集合。
