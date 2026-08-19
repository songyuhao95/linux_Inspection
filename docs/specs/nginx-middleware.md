# Nginx 中间件监控（nginx-p0-v1）

## 范围

Nginx 中间件模块是第一个中间件适配器，指标按《安徽农金Nginx、Keepalived运维
巡检手册v1.0.docx》（Nginx 手册 sha256[:8]=72b0834d）P0/P1 指标表转写。
模块文件：`inspect/modules/nginx.py`；阈值基线：`inspect/data/thresholds/nginx-p0-v1.yaml`。

## 指标清单（8 个）

| metric_id | 名称 | 命令 | 文档来源 |
| --- | --- | --- | --- |
| `local.nginx.process.present` | Nginx 进程存在性 | `pgrep -fa 'nginx: master\|nginx: worker\|/usr/sbin/nginx\|/opt/nginx/sbin/nginx'` | P0「Nginx本节点服务」 |
| `local.nginx.config.valid` | 配置有效性 | `{nginx_bin} -t -c {nginx_conf}` | P0「Nginx配置有效性」 |
| `local.nginx.port.listening` | 端口监听与本地访问 | `ss -tlnp \| grep ':{nginx_port}'; curl -sS -I http://127.0.0.1:{nginx_port}/` | P0「Nginx端口与本地访问」 |
| `local.nginx.error_log.key_evidence` | 关键日志 | `ls -1 {nginx_error_log}; tail -n 1000 {nginx_error_log} \| egrep -i 'emerg\|alert\|crit\|error\|...'` | P0「关键日志」 |
| `local.nginx.connections.status` | 连接状态（stub_status） | `curl -sS http://127.0.0.1:{nginx_port}/nginx_status` | P1「Nginx连接状态」 |
| `local.nginx.access_log.status_codes` | 访问日志状态码 | `ls -1 {nginx_access_log}; tail -n 1000 {nginx_access_log} \| grep -E ' [1-5][0-9][0-9] '` | P1「访问日志状态码」 |
| `local.nginx.config.baseline` | 配置基线 | `ls -1 {nginx_conf}; grep -E 'worker_processes\|...\|limit_conn' {nginx_conf}` | P1「Nginx配置基线」 |
| `local.nginx.security.baseline` | 安全配置基线 | `ls -1 {nginx_conf}; grep -E 'server_tokens\|autoindex\|...' {nginx_conf}` | P1「安全配置基线」 |

所有命令均为只读、无 `$`/反引号，通过 `inspect/ansible_runner.py` 的 allow-list 校验；
HTTP 探测使用 `curl`（手册要求），仅限 `local.nginx.*` 指标模板。

## 进程发现与白名单

默认巡检先执行 `local.nginx.process.present`（进程发现）：

- **运行中**：采集全部 8 个 Nginx 指标；
- **未运行且不在白名单**：丢弃该主机全部 Nginx 指标（该主机不是 Nginx 节点，跳过）；
- **未运行且在白名单**：只保留 `local.nginx.process.present`，判定 **CRIT 未运行**
  （normalize 复用进程存在性判定：absent → CRIT）；
- **进程发现采集失败**（无权限等）：保留全部 Nginx 指标为 UNKNOWN+error（不伪装结论）。

白名单来自仓库根 `nginx.yml` 的 `whitelist` 列表（模板 `nginx.yml.example`）；
选择逻辑实现为 `ansible_runner.select_nginx_metrics`，在 local 与 Ansible 两条执行
路径的结果组装阶段统一应用，host-result-v1 的 `host.product_profiles` 据此标记 `nginx`。

## 配置（nginx.yml）

字段：`nginx_bin`、`nginx_conf`、`nginx_error_log`、`nginx_access_log`、
`nginx_port`、`whitelist`。缺省值来自手册环境信息（`/opt/nginx`、端口 `8010`）。
`nginx.yml` 被 `.gitignore` 忽略；现场信息通过 `nginx.yml.example` 模板复制配置。

## 报表集成

- **Excel**：新增 `nginx` Sheet（`SHEET_NGINX`），只列 `local.nginx.*` 指标，字段与
  `Local` 一致；Sheet 顺序 Overview / Local / nginx / Errors-Evidence。
- **HTML**：`render_html._middleware_values` 按 metric_id 前缀 `local.nginx.` 归入
  「nginx」中间件维度；左侧中间件/监控指标多选筛选与按中间件/按监控指标分组自动生效；
  Linux 基础指标仍归「Linux 基础」。

## CLI

- 默认（无 `--nginx`）：`linux_basic` + 全部已注册中间件（当前 `nginx`）；
- `--nginx`：只巡检 Nginx 中间件（仍保留 Linux 主机基础指标）；
- 未来新增中间件时，`middleware_module_ids()` 自动纳入默认巡检集合。
