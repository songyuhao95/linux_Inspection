# Linux 中间件巡检脚本

这是一个面向 Linux 主机和常见中间件的只读巡检工具。项目通过 `inspect.sh` 统一入口，使用仓库内置的 Python 3.12 和 Ansible 运行时执行巡检，不依赖控制机预先安装的系统 Python 或 Ansible。

当前已实现的巡检范围包括：

- Linux 主机基础指标；
- Nginx；
- Keepalived；
- Elasticsearch；
- 标准输出摘要；
- Excel 报表；
- 单文件离线 HTML 报表。

> `app` 目录本身就是 Git 仓库根目录。因此在 GitHub 页面中会直接看到 `inspect.sh`、`inspect/`、`runtime/` 等内容，而不会再看到一层名为 `app/` 的目录。

## 1. 目录结构

```text
.
├── inspect.sh                 # 巡检入口
├── inspect.conf               # 中间件路径、端口、基线等运行参数
├── inspect/                   # Python 巡检程序
├── inventory/
│   └── hosts.ini              # 不含真实凭据的公开 inventory 示例
├── runtime/
│   ├── bin/python3.12         # Linux 控制端 Python 3.12
│   ├── bin/python3.12.exe     # Windows 开发环境兼容运行时
│   ├── ansible/               # 随项目打包的 Ansible 运行时
│   └── manifest.json          # 运行时版本和哈希清单
├── out/                       # 运行后生成，已被 Git 忽略
└── .runtime/                  # 临时 inventory/playbook，已被 Git 忽略
```

`runtime/` 是可部署运行时的一部分，不能只复制 Python 文件而遗漏 `runtime/ansible/`、动态库、标准库或 `manifest.json`。

## 2. 快速开始

### 2.1 前置条件

控制端需要满足：

- Linux 或 WSL 控制环境；
- Bash；
- 能够运行仓库内置的 Python 3.12；
- 远程模式下能够通过 SSH 连接目标主机。

Linux 目标主机不需要安装 Ansible；Ansible 由控制端的 `runtime/` 提供。首次从 Git 克隆后，如果文件系统或 Git 配置没有保留执行权限，可以执行：

```bash
chmod +x inspect.sh runtime/bin/python3.12
```

请从仓库根目录运行命令。入口脚本会根据自身位置寻找 `runtime/`，但报表默认目录和 `inspect.conf` 的读取位置仍然与运行目录有关，详见后文。

### 2.2 执行本机巡检

如果要巡检当前这台控制主机，使用 `--local`：

```bash
bash inspect.sh --local
```

`--local` 走本机只读探测，不调用远程 SSH，也不要求配置 `INSPECT_REMOTE_USER`。它会始终包含 Linux 基础指标，并根据选项决定是否检查中间件。

### 2.3 执行远程巡检

远程模式使用 `-H/--hosts` 或 `-i/--inventory`，由项目内 Ansible 执行。

使用主机名、IP 或默认 inventory 中的主机组：

```bash
bash inspect.sh -H inspection
```

指定多个主机：

```bash
bash inspect.sh -H 192.0.2.10,192.0.2.11
```

远程模式必须明确认证方式。使用 SSH 用户并让 Ansible 在终端交互式询问密码：

```bash
INSPECT_REMOTE_USER=inspect-user INSPECT_ASK_PASS=1 \
bash inspect.sh -H inspection
```

如果使用 SSH 密钥、SSH agent 或 `~/.ssh/config`，可以只指定用户：

```bash
INSPECT_REMOTE_USER=inspect-user bash inspect.sh -H inspection
```

密码不要写进命令历史、公开 inventory、`inspect.conf`、报表或 Git 提交中。

### 2.4 生成报表

生成本机 HTML：

```bash
bash inspect.sh --local --html out/local-smoke.html
```

生成本机 Excel：

```bash
bash inspect.sh --local --excel out/local-smoke.xlsx
```

同时生成 Excel 和 HTML：

```bash
bash inspect.sh --local \
  --excel out/local-smoke.xlsx \
  --html out/local-smoke.html
```

远程巡检也可以使用相同的报表选项：

```bash
INSPECT_REMOTE_USER=inspect-user INSPECT_ASK_PASS=1 \
bash inspect.sh -H inspection \
  --excel out/inspection.xlsx \
  --html out/inspection.html
```

Excel 渲染需要运行时中可用的 `xlsxwriter`。如果 Excel 渲染失败，HTML 和事实源仍可能已经生成；请以终端中的错误信息和退出码为准。

## 3. 主机选择和 inventory

### 3.1 `--local`

```bash
bash inspect.sh --local
```

- 只巡检当前控制主机；
- 使用本机直接探测路径；
- 不调用 Ansible 远程连接；
- 不能与 `-H`、`-i` 同时使用。

### 3.2 `-H/--hosts`

```bash
bash inspect.sh -H inspection
bash inspect.sh -H 192.0.2.10,192.0.2.11
```

`-H` 的值可以是：

- 默认 inventory 中的主机组名；
- inventory 中的主机别名；
- IP 或能够由控制端解析的主机名；
- 逗号分隔的多个主机或组。

处理顺序如下：

1. 如果 `inventory/hosts.local.ini` 是有效 inventory，优先使用它；
2. 否则尝试使用有实际主机条目的 `inventory/hosts.ini`；
3. 如果两个文件都只是注释模板，则生成临时 inventory，把 `-H` 的值当作主机名或 IP 交给 Ansible。

因此，在没有私有 inventory 时，`-H inspection` 会把 `inspection` 当作要连接的主机名，而不是自动创建一个名为 `inspection` 的主机组。需要确保该名称能够被控制端解析，或者直接传 IP。

### 3.3 `-i/--inventory`

使用指定的完整 inventory：

```bash
bash inspect.sh -i inventory/hosts.local.ini
```

只选择某个组或主机：

```bash
bash inspect.sh \
  -i inventory/hosts.local.ini \
  --limit inspection
```

选择 inventory 中全部主机：

```bash
bash inspect.sh -i inventory/hosts.local.ini --all
```

`--limit` 和 `--all` 只与 `-i/--inventory` 搭配使用。

### 3.4 私有 inventory 示例

仓库内的 [inventory/hosts.ini](inventory/hosts.ini) 只是公开示例，不能填写真实密码。现场配置请复制为被 Git 忽略的 `inventory/hosts.local.ini`：

```bash
cp inventory/hosts.ini inventory/hosts.local.ini
chmod 600 inventory/hosts.local.ini
```

然后按现场环境填写，例如：

```ini
[inspection]
node-01 ansible_host=192.0.2.10
node-02 ansible_host=192.0.2.11

[inspection:vars]
ansible_connection=ssh
ansible_user=inspect-user
```

认证可以来自 SSH key、SSH agent、SSH 配置或交互式 `--ask-pass`。如果现场确实使用 inventory 中的 Ansible 密码变量，必须确保该文件权限严格、不会被提交，并遵守现场的秘密管理要求。

`inventory/hosts.local.ini` 和 `inventory/*.local.ini` 已加入 `.gitignore`。请不要把真实账号、密码、私钥路径或 token 写入公开的 `inventory/hosts.ini`。

## 4. 中间件选择

默认情况下，脚本执行 Linux 基础指标和当前已注册的全部中间件指标。

只检查 Nginx：

```bash
bash inspect.sh --local --nginx
```

只检查 Keepalived：

```bash
bash inspect.sh --local --keepalived
```

只检查 Elasticsearch：

```bash
bash inspect.sh --local --elasticsearch
```

远程模式同样适用：

```bash
INSPECT_REMOTE_USER=inspect-user bash inspect.sh -H inspection --nginx
```

无论选择哪个中间件，Linux 基础指标都会保留。`--nginx`、`--keepalived` 和 `--elasticsearch` 互斥，不能同时指定多个。

## 5. 命令选项参考

| 选项 | 作用 |
| --- | --- |
| `--local` | 直接巡检当前控制主机，不使用远程 Ansible |
| `-H, --hosts VALUE` | 按主机组、主机名或 IP 选择远程目标 |
| `-i, --inventory PATH` | 使用指定 inventory 文件 |
| `--limit PATTERN` | 在指定 inventory 中按主机或组筛选 |
| `--all` | 选择指定 inventory 中的全部主机 |
| `--parallel N` | 远程并行主机数，范围为 1–10 |
| `--nginx` | Linux 基础指标 + Nginx |
| `--keepalived` | Linux 基础指标 + Keepalived |
| `--elasticsearch` | Linux 基础指标 + Elasticsearch |
| `-e, --excel [PATH]` | 生成 Excel；不写路径时写入当前目录 |
| `--html [PATH]` | 生成离线 HTML；不写路径时写入当前目录 |
| `--fail-on critical` | 任一指标为 CRIT 时以业务告警退出码结束 |
| `--list-metrics` | 列出已实现指标，不连接主机 |
| `--info METRIC_ID` | 查看单个指标定义，不连接主机 |

查询模式示例：

```bash
bash inspect.sh --list-metrics
bash inspect.sh --info local.cpu.load_1m
```

`--list-metrics` 和 `--info` 是只读查询，不能与主机选择、报表或巡检参数混用。

## 6. 输出和退出码

### 6.1 输出目录

默认事实源写入当前工作目录下的 `out/`：

```text
out/
└── <inspection-id>/
    ├── hosts/
    │   └── <host>.json
    └── ...
```

每个主机的 JSON 是报表和后续处理使用的事实源。Excel 和 HTML 报表只读取已经落盘的事实源，不会为了渲染报表再次连接目标主机。

如果在 `/data/inspect/linux_Inspection` 目录中运行且没有通过参数指定绝对路径，默认输出通常位于：

```text
/data/inspect/linux_Inspection/out/
```

如果希望输出到 `/data/inspect/out/`，请显式指定路径：

```bash
bash inspect.sh --local \
  --excel /data/inspect/out/local-smoke.xlsx \
  --html /data/inspect/out/local-smoke.html
```

`out/`、`inspection-results/` 和 `.runtime/` 都是运行期目录，已被 Git 忽略。不要把生成的报表和临时 inventory 提交到仓库。

### 6.2 退出码

| 退出码 | 含义 |
| ---: | --- |
| `0` | 执行完成；默认情况下即使指标有 WARN/CRIT，也不因业务状态失败 |
| `2` | 命令参数或主机选择用法错误 |
| `10` | 技术执行失败，例如运行时、认证、连接、配置或渲染失败 |
| `20` | 使用 `--fail-on critical` 时，至少一个指标为 CRIT |

技术执行失败优先于业务告警，不能把连接失败伪装成业务结论。

## 7. `inspect.conf` 详细说明

### 7.1 文件位置和安全要求

`inspect.conf` 位于仓库根目录，脚本默认读取该文件。Linux 上首次读取时，程序会尝试将文件权限收紧为 `700`；如果权限无法满足要求，巡检会以配置错误退出。

配置文件可以包含现场路径、版本基线、服务账号和 Elasticsearch API 参数，因此建议：

```bash
chmod 700 inspect.conf
```

仓库中的版本是可公开发布的模板，其中 `192.0.2.x` 是文档保留地址，`CHANGE_ME` 是占位值。部署到现场后可以在受控副本中替换为真实值，但真实账号、密码、token、私钥和内部地址不应提交到公共 Git 仓库。

### 7.2 通用语法

每行一个参数：

```text
参数名 = 值1|值2|值3
```

规则：

- 空行和以 `#` 开头的行会被忽略；
- 参数名使用小写字母、数字和下划线，且必须以小写字母开头；
- `|` 表示多个候选值，程序按候选顺序使用；
- 单值参数不要写多个候选值；
- 候选值前后的空白会被去掉；
- 单引号和双引号可以包裹候选值；
- 当一个值本身包含 `|` 时，应使用引号包裹；
- 不要在值后面追加未被程序支持的行内注释；
- 配置拼写错误不会产生预期效果，应严格使用下面列出的参数名。

例如：

```text
nginx_bin = /usr/sbin/nginx|/usr/local/nginx/sbin/nginx
nginx_baseline = "server_tokens_off=True"|"autoindex_off=True"
```

`inspect.conf` 中的路径大多是“候选路径”，不是强制要求每台主机都存在。巡检通常优先从运行进程参数和实际配置文件发现位置；只有无法发现时，才按这里的候选顺序查找。无法发现且没有可用候选值的指标会按指标规则显示为 UNKNOWN 或被跳过，而不是伪造正常结果。

### 7.3 全局参数

#### `timeout`

```text
timeout = 3
```

统一控制 SSH 连接、能力探测、远程 shell 命令和 HTTP/curl 请求的默认超时时间，单位为秒。允许范围是 `1` 到 `60`，默认值为 `3`。

- 数值越小，巡检返回越快，但慢主机更容易被标记为 UNKNOWN；
- 数值越大，慢主机更有机会完成，但整体巡检时间会增加；
- 该参数只能是一个整数，不能写成 `3|5`。

### 7.4 Nginx 参数

#### `nginx_bin`

```text
nginx_bin = /usr/sbin/nginx|/opt/nginx/sbin/nginx|/opt/nginx-aqwh/sbin/nginx|/usr/local/nginx/sbin/nginx
```

Nginx 可执行文件候选路径。程序会优先从运行中的 Nginx master 进程参数取得实际路径；进程参数无法解析时，按这里的顺序寻找可执行文件。

#### `nginx_conf`

```text
nginx_conf = /opt/nginx-aqwh/conf/nginx.conf|/opt/nginx/conf/nginx.conf|/usr/local/nginx/conf/nginx.conf
```

Nginx 主配置文件候选路径。如果运行进程没有通过 `-c` 指明配置文件，程序会按顺序查找存在的文件。

#### `nginx_error_log`

```text
nginx_error_log = /opt/nginx-aqwh/logs/error.log|/opt/nginx/logs/error.log|/usr/local/nginx/logs/error.log
```

错误日志候选路径。进程没有通过 `-e` 指定日志、且配置文件没有解析出 `error_log` 时使用。

#### `nginx_access_log`

```text
nginx_access_log = /opt/nginx-aqwh/logs/access.log|/opt/nginx/logs/access.log|/usr/local/nginx/logs/access.log
```

访问日志候选路径。程序优先解析实际配置中的 `access_log`；只有解析不到时才使用这里的候选路径。

#### `nginx_port`

```text
nginx_port = 8010
```

Nginx 监听端口的备用值。程序优先解析实际 Nginx 配置中的 `listen` 指令，无法解析时才使用该值。

#### `nginx_version`

```text
nginx_version = nginx/1.28.0
```

允许的 Nginx 版本基线。程序从运行中的 Nginx 对应可执行文件执行 `-v` 获取实际版本，并与这里的允许值比较。需要允许多个版本时使用 `|` 分隔：

```text
nginx_version = nginx/1.28.0|nginx/1.26.3
```

#### `nginx_baseline`

```text
nginx_baseline = "server_tokens_off=True"|"autoindex_off=True"
```

Nginx 安全配置基线。每个候选项的格式是 `检查项=True/False`，多个检查项用 `|` 分隔。目前模板中的检查项含义是：

- `server_tokens_off=True`：期望关闭版本信息暴露；
- `autoindex_off=True`：期望关闭目录索引。

这里填写的是期望基线，不是直接修改 Nginx 配置的命令。巡检只读检查，不会自动改配置。

#### `nginx_whitelist`

```text
nginx_whitelist = 192.0.2.10|192.0.2.11
```

Nginx 进程必须存在的主机 IP 白名单：

- 白名单主机未发现 Nginx 进程：对应指标标记为 CRIT；
- 不在白名单的主机未运行 Nginx：跳过 Nginx 指标，不直接判定为故障；
- 多个 IP 使用 `|` 分隔。

### 7.5 Keepalived 参数

#### `keepalived_bin`

```text
keepalived_bin = /usr/sbin/keepalived|/usr/local/sbin/keepalived|/opt/keepalived/sbin/keepalived
```

Keepalived 可执行文件候选路径。程序优先从运行进程参数发现，无法发现时按顺序查找。

#### `keepalived_conf`

```text
keepalived_conf = /opt/keepalived/conf/keepalived.conf|/etc/keepalived/keepalived.conf|/usr/local/etc/keepalived/keepalived.conf
```

Keepalived 主配置文件候选路径。进程通过 `-f` 指定的路径优先。

#### `keepalived_log`

```text
keepalived_log = /opt/keepalived/logs/keepalived.log|/var/log/keepalived.log
```

Keepalived 日志候选路径。Keepalived 常使用 syslog，因此程序也会尝试从运行环境中发现日志位置；无法发现时才使用这里的候选值。

#### `keepalived_vip`

```text
keepalived_vip = 192.0.2.253
```

VIP 候选值。程序优先从实际 Keepalived 配置中的 `virtual_ipaddress` 读取，这里是兜底值。

#### `keepalived_port`

```text
keepalived_port = 8010
```

用于验证 VIP 后端 Nginx 或业务入口的访问端口。Keepalived 本身通常不监听 HTTP，这个参数不是 Keepalived 的监听端口。

#### `keepalived_version`

```text
keepalived_version = keepalived/2.2.8
```

允许的 Keepalived 版本基线。程序从运行中的 Keepalived 二进制执行 `-v` 获取实际版本。

#### `keepalived_baseline`

```text
keepalived_baseline = state=True|interface=True|virtual_router_id=True|priority=True|advert_int=True|virtual_ipaddress=True|script=True|track_script=True
```

Keepalived 配置基线键值。当前模板检查以下关键项是否存在或满足基线要求：

- `state`；
- `interface`；
- `virtual_router_id`；
- `priority`；
- `advert_int`；
- `virtual_ipaddress`；
- `script`；
- `track_script`。

#### `keepalived_whitelist`

```text
keepalived_whitelist = 192.0.2.10|192.0.2.11
```

Keepalived 进程白名单，判断规则与 `nginx_whitelist` 相同：白名单主机未运行 Keepalived 时为 CRIT，其他主机按跳过规则处理。

### 7.6 Elasticsearch 参数

#### 路径类参数

```text
elasticsearch_bin = /opt/elasticsearch/bin/elasticsearch|/usr/local/elasticsearch/bin/elasticsearch|/usr/share/elasticsearch/bin/elasticsearch
elasticsearch_conf = /opt/elasticsearch/conf/elasticsearch.yml|/opt/elasticsearch/config/elasticsearch.yml|/etc/elasticsearch/elasticsearch.yml|/usr/local/etc/elasticsearch/elasticsearch.yml
elasticsearch_log = /opt/elasticsearch/logs/es-prod-cluster.log|/opt/elasticsearch/logs/elasticsearch.log|/var/log/elasticsearch/elasticsearch.log
elasticsearch_gc_log = /opt/elasticsearch/logs/gc.log|/opt/elasticsearch/logs/gc.log.*|/var/log/elasticsearch/gc.log
elasticsearch_data = /opt/elasticsearch/data|/var/lib/elasticsearch
elasticsearch_backup = /opt/elasticsearch/backup|/var/backups/elasticsearch
```

这些参数分别用于：

- `elasticsearch_bin`：Elasticsearch 启动程序；优先从运行参数中的 `-Des.path.home` 或实际命令发现；
- `elasticsearch_conf`：`elasticsearch.yml` 候选路径；优先从 `-Des.path.conf` 或运行目录发现；
- `elasticsearch_log`：主日志候选路径；优先从 `-Des.path.logs` 和 `path.logs` 发现；
- `elasticsearch_gc_log`：GC 日志候选路径，用于检查 Full GC、暂停和 OutOfMemory；支持通配符路径作为候选；
- `elasticsearch_data`：数据目录候选路径，用于磁盘和数据目录说明；
- `elasticsearch_backup`：备份目录候选路径，用于备份目录检查和说明。

实际运行参数和 `elasticsearch.yml` 中已经声明的路径优先于这些兜底候选值；其中
`/opt/elasticsearch/conf/elasticsearch.yml` 覆盖常见 tar 包部署的实际配置目录。

#### `elasticsearch_endpoint`

```text
elasticsearch_endpoint = https://127.0.0.1:9200
```

Elasticsearch HTTP API 的兼容地址。程序优先从运行中的 `elasticsearch.yml` 和本机监听 socket 解析可连接地址；只有无法发现具体监听地址时才按候选顺序使用此值。每个候选值必须包含自己的协议和端口，使用时保持原值，不会再拼接默认地址或端口。

#### `elasticsearch_http_port`

```text
elasticsearch_http_port = 9200
```

HTTP API 端口的兜底值。实际配置中的 `http.port` 优先。

#### `elasticsearch_transport_port`

```text
elasticsearch_transport_port = 9300
```

节点传输端口的兜底值。实际配置中的 `transport.port` 优先。

#### `elasticsearch_version`

```text
elasticsearch_version = 8.17.0
```

Elasticsearch 版本基线。程序通过运行实例的根 API `version.number` 获取实际版本并进行比较。多个允许版本可以使用 `|` 分隔。

#### `elasticsearch_expected_nodes`

```text
elasticsearch_expected_nodes = 3
```

期望的集群节点数量，用于集群健康和 `_cat/nodes` 在线节点数判定。应填写该目标集群正常运行时的节点数。

#### `elasticsearch_seed_hosts`

```text
elasticsearch_seed_hosts = 192.0.2.101:9300|192.0.2.102:9300|192.0.2.103:9300
```

集群发现的 `seed_hosts` 基线，多个节点用 `|` 分隔。它用于检查发现配置是否符合预期，不会修改 Elasticsearch 配置。

#### `elasticsearch_system_user`

```text
elasticsearch_system_user = es
```

Elasticsearch 运行系统用户。程序使用它作为读取该用户 `ulimit` 等运行条件的参考，常见值为 `es`。

#### `elasticsearch_auth_file`

```text
elasticsearch_auth_file = /opt/elasticsearch/.inspect-netrc|/home/es/.config/inspect-es.netrc
```

HTTP API 认证的 netrc 文件候选路径。当 API 用户名或密码没有直接配置时，可作为认证兜底。该文件应只存在于目标环境，并设置严格权限；不要提交到仓库。

#### `elasticsearch_api_user` 和 `elasticsearch_api_password`

```text
elasticsearch_api_user = elastic
elasticsearch_api_password = CHANGE_ME
```

Elasticsearch HTTP API 的认证账号和密码，与 SSH 登录账号是两套不同的认证信息：

- SSH 用户由 inventory 或 `INSPECT_REMOTE_USER` 提供；
- Elasticsearch API 用户由这两个参数提供；
- `CHANGE_ME` 是公开模板占位值，不应作为真实密码使用；
- 真实密码只能保存在现场受控配置中，不能提交到 GitHub、报告或日志。

远程 API 指标会通过 Ansible 任务环境传递认证信息，不把它写进事实源、命令参数或报表；本机模式也会使用进程环境处理。

#### `elasticsearch_cacert` 和 `elasticsearch_cert`

```text
elasticsearch_cacert = /opt/elasticsearch/conf/certs/http_ca.crt|/opt/elasticsearch/config/certs/http_ca.crt|/etc/elasticsearch/certs/http_ca.crt
elasticsearch_cert = /opt/elasticsearch/conf/certs/http_ca.crt|/opt/elasticsearch/config/certs/http_ca.crt|/etc/elasticsearch/certs/http_ca.crt
```

- `elasticsearch_cacert`：HTTPS API 使用 `curl --cacert` 的 CA 证书候选路径；
- `elasticsearch_cert`：使用 `openssl` 检查证书有效期的候选路径，并可作为 CA 路径兜底。

程序会优先从 Elasticsearch 运行配置发现证书位置。

#### `elasticsearch_snapshot_repo`

```text
elasticsearch_snapshot_repo = backup
```

快照仓库名称，用于调用 `/_snapshot/<repo>/_verify` 检查仓库。未配置或目标不存在时，该项可能显示为 UNKNOWN；巡检不会创建、删除或修改快照。

#### `elasticsearch_whitelist`

```text
elasticsearch_whitelist = 192.0.2.101|192.0.2.102|192.0.2.103
```

Elasticsearch 进程白名单。白名单主机未发现 Elasticsearch 进程时标记 CRIT，其他主机按跳过规则处理。

## 8. 常见问题

### 报错 `project-local Python 3.12 is missing`

通常不是文件真的不存在，而是 Linux 文件没有执行权限。检查并修复：

```bash
chmod +x inspect.sh runtime/bin/python3.12
```

然后确认使用的是最新仓库版本：

```bash
git pull --ff-only origin main
```

### 报错 `remote_user_missing`

说明已经进入远程执行流程，但没有得到远程 SSH 用户。使用 `INSPECT_REMOTE_USER`、私有 inventory、SSH key 或交互式 `INSPECT_ASK_PASS=1`。

如果目标就是当前控制主机，请改用：

```bash
bash inspect.sh --local
```

### 报表没有出现在预期目录

默认 `out/` 是相对于当前工作目录的，而不是固定相对于脚本所在目录。请使用绝对路径明确指定：

```bash
bash inspect.sh --local \
  --excel /data/inspect/out/local-smoke.xlsx \
  --html /data/inspect/out/local-smoke.html
```

### 某个中间件没有运行但没有被判定为 CRIT

请检查对应的 `*_whitelist`。只有列入白名单的主机才要求该中间件进程必须存在；未列入白名单的主机通常会跳过对应中间件指标。

### 指标显示 UNKNOWN

UNKNOWN 通常表示采集命令超时、目标文件不存在、权限不足、服务未暴露所需 API 或无法从运行环境发现路径。先查看终端错误摘要，再检查对应的 `inspect.conf` 候选路径、权限和服务实际配置。

## 9. 只读和安全边界

- 巡检只读取进程、配置、日志、端口、版本和 API 状态，不修改目标主机业务配置；
- 入口脚本禁止回退到系统 Python，避免运行时版本漂移；
- 远程执行必须显式开启并提供认证边界；
- 公开 inventory 和公开 `inspect.conf` 只能保存模板和占位值；
- 真实认证信息放在目标环境的私有文件、SSH agent 或交互式输入中；
- 报表和事实源不应包含密码、私钥或未脱敏的秘密；
- 生成目录 `out/`、`.runtime/` 不应提交到 Git；
- 修改配置基线前，应先确认该基线代表目标环境的正常状态。
