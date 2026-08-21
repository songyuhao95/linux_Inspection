# Elasticsearch 中间件监控规格（elasticsearch-p0-p1-v1）

本模块依据 `linux-docx/安徽农金Elasticsearch运维巡检手册v1.0.docx` 的 P0 表 62、P1 表 65 实现。每次运行始终包含 Linux 主机基础指标；选择 Elasticsearch 后额外采集专属指标：进程发现、版本、集群健康、在线节点、节点 CPU/内存/磁盘、磁盘水位线、未分配分片、服务与 9200/9300 端口、Heap/GC、线程池拒绝、动态设置、发现配置、索引健康、慢日志、安全账号、HTTPS 证书、快照仓库和系统参数。

## 进程发现与路径

进程模式同时识别 Elasticsearch 启动脚本和 `org.elasticsearch.bootstrap.Elasticsearch` JVM。运行中的实例优先提供 `-Des.path.home`、`-Des.path.conf`、`-Des.path.logs`，并从配置推导 HTTP/Transport 端口、证书和日志目录。只有进程参数无法得到路径时才按 `inspect.conf` 的 `elasticsearch_*` 候选值顺序查找；全部没有时相关指标为 UNKNOWN，不把固定路径误当成真实实例。

没有 Elasticsearch 进程的主机默认跳过 ES 指标。`elasticsearch_whitelist` 中的主机如果没有进程，只保留 `local.elasticsearch.process.present` 并判定 CRIT“未运行”。当前 v1 以一台主机一个运行中实例为默认模型；多实例时选择首个匹配实例并报告实际发现路径，后续可按 `-Des.path.data`/`-Des.path.conf` 扩展实例维度。

## API 认证与判定

API 使用运行中 Elasticsearch 配置文件的监听地址和 `http.port`：优先读取
`http.host`、`http.bind_host`、`network.bind_host`、`network.host`、
`network.publish_host`，再按 `inspect.conf` 的路径候选查找配置文件。`elasticsearch_endpoint`
仅作为兼容配置，不覆盖运行配置中的监听地址。`0.0.0.0`、`::`、`_site_` 等绑定选择器不是可连接地址，
解析不到具体地址时指标为 UNKNOWN，不再偷偷改连 127.0.0.1。证书候选路径由
`elasticsearch_cacert` 配置，实际请求优先使用 `curl --cacert`；没有可读 CA 时才回退
到兼容自签名证书的 `-k`。HTTP API 账号密码由私有 `inspect.conf` 的
`elasticsearch_api_user` 和 `elasticsearch_api_password` 提供。远程 API 指标使用 Ansible
`raw` 任务；控制端通过 Ansible env lookup 把私密值临时注入远端命令环境，因此受控端不需要
安装 Python 或 Ansible，playbook 本身不保存
明文密码。本地模式使用进程环境，curl 使用 `-u "$INSPECT_ES_API_USER:$INSPECT_ES_API_PASSWORD"`；
规范化事实源和报表会对 command 脱敏，不保留明文密码。GitHub 中跟踪的 `inspect.conf` 只能保留 `CHANGE_ME` 占位符，
真实密码不得提交；也可以继续使用目标机 `elasticsearch_auth_file` netrc 作为认证兜底。
未授权 401/403、连接失败、配置/日志/证书不可读均为 UNKNOWN，绝不会默认通过。

端口优先从运行配置的 `http.port`/`transport.port` 读取，随后使用 `inspect.conf` 9200/9300 候选；HTTP 请求组合为运行配置解析出的监听地址和 `http.port`。集群 `green`、期望节点数达到、活跃分片 100% 为正常；`yellow` 为 WARN，`red` 或节点严重缺失为 CRIT。未分配主分片为 CRIT，未分配副本或初始化中为 WARN。慢日志未启用时显示“未配置”，不默认判定为故障。

### 三个指标的实际取值命令

以下命令是脱敏后的复现形式；`ES_ENDPOINT`、`ES_CA`、`ES_PASSWORD` 使用现场实际值，
密码不要直接写入命令历史。脚本会先从运行进程的 `-Des.path.*` 和配置文件发现端口、证书，
再按 `inspect.conf` 候选兜底；所有 Elasticsearch curl 请求只访问受控端本机配置的监听地址，
不会访问控制端或 inventory 中的其他主机。

```bash
# 1. 版本：读取运行实例根 API 的 version.number，不再执行 bin/elasticsearch --version，
#    避免某些 tar 安装的启动脚本启动 JVM 或阻塞。
curl -sS --connect-timeout 3 --max-time 3 \
  --cacert "$ES_CA" -u "elastic:$ES_PASSWORD" \
  "https://$ES_LISTEN_HOST:9200/" -w '\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\n'

# 2. 索引健康与规模：v 只返回表头表示当前没有索引，这是“0 个索引”的有效结果。
curl -sS --connect-timeout 3 --max-time 3 \
  --cacert "$ES_CA" -u "elastic:$ES_PASSWORD" \
  "https://$ES_LISTEN_HOST:9200/_cat/indices?v&h=health,index,pri,rep,docs.count,store.size&s=store.size:desc" \
  -w '\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\n'

# 3. 快照仓库：先列出仓库，再验证 inspect.conf 中的仓库名（以下以 backup 为例）。
curl -sS --connect-timeout 3 --max-time 3 \
  --cacert "$ES_CA" -u "elastic:$ES_PASSWORD" \
  "https://$ES_LISTEN_HOST:9200/_snapshot/_all?pretty" -w '\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\n'
curl -sS --connect-timeout 3 --max-time 3 -X POST \
  --cacert "$ES_CA" -u "elastic:$ES_PASSWORD" \
  "https://$ES_LISTEN_HOST:9200/_snapshot/backup/_verify?pretty" \
  -w '\nINSPECT_ELASTICSEARCH_HTTP_STATUS=%{http_code}\n'
```

上述命令中的 `3` 应与私有 `inspect.conf` 的 `timeout` 保持一致。根 API 和 CAT API 返回 HTTP 401/403、网络错误或格式异常会是 UNKNOWN。索引接口只有表头时
按 `indices=0; red=0; yellow=0` 判定 OK；快照仓库不存在时 Elasticsearch 会返回
`repository_missing_exception`，巡检将其作为“仓库缺失”业务 WARN，而不是误报为认证失败。

## 使用

```bash
bash inspect.sh --local --elasticsearch
bash inspect.sh -H inspection --elasticsearch --html out/elasticsearch.html --excel out/elasticsearch.xlsx
```

不带 `--elasticsearch` 时默认执行所有已注册中间件；与 `--nginx`、`--keepalived` 一样，它是只选择 Elasticsearch 的快捷方式。Excel 输出 `elasticsearch` Sheet，HTML 自动进入中间件筛选、监控指标筛选和按中间件/指标分组。
