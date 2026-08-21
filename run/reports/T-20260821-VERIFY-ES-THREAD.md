# T-20260821-VERIFY-ES-THREAD 只读复核报告

- run_id: `run-20260821-es-thread-refactor-001`
- task_id: `T-20260821-VERIFY-ES-THREAD`
- phase: `verify`
- contract_id: `contract-20260821-es-thread-review-v1`
- contract_version: `2`
- contract_sha256: `sha256:e90916ec860540dacf5b06787dcb5a23e920526d7fd5fe2e8769331a11b22577`
- 复核范围：当前工作树中的 `inspect/ansible_runner.py`、`inspect/normalize.py`、`inspect/cli.py`、测试及并发执行文档。
- 安全边界：未连接远程主机；未读取、输出或使用任何凭据；未修改实现文件。

## 结论摘要

- P0：无。
- P1：5 项，主要涉及 Elasticsearch 发现优先级/状态契约，以及临时 inventory 在多线程清理时的竞态。
- P2：3 项，主要是测试和文档仍残留旧的 1～3 并发假设，且新线程/ES 回归场景覆盖不足。
- 当前 ES 专项测试通过，但指定的 ES+runner 回归命令失败，失败原因是旧并发测试仍要求 `serial: 3`。

## P1 findings

### P1-1：`path.logs` 优先级仍然错误，可能读取错误日志目录

- 文件：`inspect/ansible_runner.py:859-865`
- 现状：先从 JVM 参数取 `-Des.path.logs`，随后在 `es_home` 存在时立即回退到 `$es_home/logs`；只有在此之后才解析有效配置文件中的 `path.logs`。
- 影响：当 Elasticsearch launcher/server 没有显式 `-Des.path.logs`、且 `$ES_HOME/logs` 目录存在，而 `elasticsearch.yml` 配置了另一个 `path.logs` 时，slowlog/GC/日志证据会指向错误目录。结果可能是错误的 OK、错误的 UNKNOWN，或漏掉真实日志。
- 建议：优先级固定为“JVM 显式 `-Des.path.logs` > 已发现配置文件 `path.logs` > inspect.conf 兜底”；仅在前两者均缺失时使用 `$ES_HOME/logs`，并对相对路径按 Elasticsearch 的路径基准解析。增加生成命令的断言测试。

### P1-2：监听地址没有真正实现声明的配置优先级

- 文件：`inspect/ansible_runner.py:878-883`
- 现状：一条 `sed` 命令同时输出 `http.host`、`http.bind_host`、`network.bind_host`、`network.host`、`network.publish_host`，再用 `head -n 1` 取“配置文件中最先出现”的值。
- 影响：代码注释声明了 HTTP 专用配置优先于 network 配置，但实现实际服从文件行顺序。若 `network.host` 出现在 `http.host` 前，会连接错误地址；多地址/通配地址混用时也可能把非实际 HTTP 端点当成 API 端点。
- 建议：分别读取并按明确顺序选择：`http.host` → `http.bind_host` → `network.publish_host` → `network.host`；对数组逐项过滤通配符，必要时再用本机 `ss` 的具体监听地址校验。为“network.host 在前、http.host 在后”的配置增加回归测试。

### P1-3：版本解析在 HTTP 错误后仍允许通用版本号兜底，存在误通过路径

- 文件：`inspect/normalize.py:952-970`
- 现状：`parse_elasticsearch_version()` 捕获 `_es_json()` 的任意 `ParseError` 后，继续用 `Version:` 或任意三段版本号正则解析。
- 影响：只要 HTTP 401/403、JSON 解析失败或传输错误输出中包含类似 `8.17.0` 的文本，就可能被当成有效版本，而不是 UNKNOWN。该行为违反“HTTP 错误不能变成业务值”的要求。
- 建议：真实命令带有 `INSPECT_ELASTICSEARCH_HTTP_STATUS` 时，非 2xx 应立即保留 ParseError，禁止正则兜底；仅对明确的无 HTTP 标记 fixture/离线输入保留兼容解析，并在测试中区分两种路径。

### P1-4：HTTP 状态标记要求在 ES 解析器之间不一致

- 文件：`inspect/normalize.py:1090-1105`（heap/GC）、`1153-1166`（security）、`1184-1215`（snapshot）
- 现状：`_es_json()` 与 `_es_cat_rows()` 要求 HTTP 状态标记；但 heap/GC、security、snapshot 解析器只在“存在且 >=400 的状态”时失败，缺少状态时仍可能解析返回内容。
- 影响：生成命令改动、callback 截断、代理异常或错误输出缺少 marker 时，部分 ES 指标可能继续产生业务值；状态契约不统一，难以证明“不是默认通过”。
- 建议：所有 API 类指标统一要求状态 marker；允许空索引、无快照仓库、未配置 slowlog 等业务空结果时，也要在 2xx marker 下走显式业务分支。补充“无 marker”“curl transport error”“401/500”的逐解析器测试。

### P1-5：显式 IP 临时 inventory 在多线程 worker 清理时存在竞态

- 文件：`inspect/ansible_runner.py:1818-1867`、`1996-2025`、`2883-2915`
- 现状：`resolve_host_selection()` 对无默认 inventory 的 `-H ip1,ip2` 会生成一个共享临时 inventory（`kind="hosts"`）。每个线程的 `prepare_run()` 将该共享 inventory 加入 `cleanup_paths`；每个 `_execute_real()` 完成后都会删除它。
- 影响：先完成的线程可能在其他线程启动 Ansible 或读取 inventory 前删除共享文件，导致其他主机出现 inventory/连接失败；同时会产生非确定性 cleanup 诊断。这与“一主机一个 playbook、线程并行”的可靠性契约冲突。
- 建议：临时 inventory 由父级统一创建和最终清理，worker 只清理自己的 playbook；或者每个 worker 生成独立单主机 inventory。增加显式 IP、至少 2 台主机、不同完成时序的并发测试。

## P2 findings

### P2-1：指定回归测试仍保留旧的 `serial: 3` 契约，当前必然失败

- 文件：`tests/test_ansible_runner.py:173-180`
- 现状：测试调用 `generate_playbook(..., parallel=3)`，断言 `serial: 3`，并以旧的“playbook 并发范围”错误信息为断言目标。
- 证据：执行 `python -m pytest tests/test_elasticsearch.py tests/test_ansible_runner.py -q` 返回码 1；Elasticsearch 测试通过，唯一失败为 `test_playbook_parallel_is_explicit_and_bounded`，因为当前实现正确拒绝 `parallel=3` 的单主机 playbook。
- 建议：改为断言每个 playbook 永远 `serial: 1`，`parallel=2/3/10` 只由 runner 线程池消费，`parallel=11` 被拒绝；同步更新错误信息断言。

### P2-2：线程池和“不可达主机不执行 bundle”没有行为级测试

- 文件：`inspect/ansible_runner.py:2920-2980`；测试目录中未发现 `ThreadPoolExecutor`、`_run_one_host` 或 `max_workers=10` 的测试。
- 现状：源码可见 `ThreadPoolExecutor(max_workers=min(parallel, len(hosts), 10))`，且 worker 生成单主机 playbook；但没有测试最大并发、结果顺序、异常传播、每个 worker 的单主机 limit，也没有测试不可达 probe 后 bundle 没有执行。
- 建议：加入可控 fake worker/屏障测试，验证最大 active worker 不超过 10、主机结果稳定按 inventory 顺序返回；加入 callback/playbook 行为测试，验证 unreachable 主机只产生主机级 CONNECTION_FAILED，bundle 不执行。

### P2-3：文档仍残留 1～3 并发/串行模型，和实现不一致

- 文件：`docs/specs/ansible-execution.md:18,35,40,44`；`README.md:29,233`
- 现状：文档仍写 `serial: 1..3`、默认逐台依次执行、`--parallel 3` 上限；README 的交接状态也保留“最多 3 台”及旧的 35.4→31.0 秒性能描述。
- 影响：运维人员会误以为 `--parallel` 修改 Ansible play 的 serial，无法获得“一个线程/一个主机/一个 playbook、上限 10”的正确操作模型。
- 建议：统一写为“每个 worker playbook 固定 `serial: 1`；控制端 ThreadPoolExecutor 负责 `--parallel 1..10`，默认 10；不可达主机在 probe 闸门处结束”。性能数字应绑定测试环境和提交版本，避免继续引用旧模型。

## 已确认的正向实现

- `inspect/ansible_runner.py:267-283` 已将 server JVM 进程发现与 launcher/path 发现拆开：process presence 仍锚定 `org.elasticsearch.bootstrap.Elasticsearch`，路径发现额外允许 `CliToolLauncher`，方向正确。
- `inspect/ansible_runner.py:845-860` 已优先从运行中 JVM 的 `-Des.path.home/conf` 和配置文件发现 ES，而不是只依赖固定目录；这是解决真实 tar 部署路径差异的正确方向。
- `inspect/ansible_runner.py:882-883` 不再强制使用 `127.0.0.1`，并在通配监听地址时尝试从本机 `ss` 获取可连接地址；符合“使用目标机实际监听地址”的要求，但仍受 P1-2 的优先级问题影响。
- `inspect/normalize.py:921-950` 已对常见 curl/连接诊断和 JSON/CAT API 的 HTTP 状态做了集中处理；方向正确，但需按 P1-4 统一到所有 API parser。
- `inspect/ansible_runner.py:1680-1697` 生成的单主机 playbook 固定 `serial: 1`，`inspect/ansible_runner.py:2948-2959` 使用控制端线程池且上限常量为 10；实现主线与新契约一致。

## 验证命令与结果

1. `python -m pytest tests/test_elasticsearch.py -q`
   - 结果：通过（8 passed；仅有 pytest cache 权限 warning，不影响测试）。
2. `python -m pytest tests/test_elasticsearch.py tests/test_ansible_runner.py -q`
   - 结果：失败（返回码 1）。
   - 失败：`tests/test_ansible_runner.py::test_playbook_parallel_is_explicit_and_bounded`。
   - 其余该命令中的测试通过；失败是旧 `parallel=3/serial:3` 假设，不是本次复核新增修改。
3. `rg -n "ThreadPoolExecutor|_run_one_host|max_workers|parallel=3|serial: 3|1～3|1-3" inspect tests docs README.md`
   - 结果：源码包含线程池和 10 上限；测试未覆盖线程池，测试/文档/README 仍命中旧 `parallel=3`/1～3 假设。

## 复核限制

- 未执行 `inspect.sh` 真实巡检。
- 未连接 192.168.0.101 或其他远程主机。
- 未读取、打印或验证任何 inventory、`inspect.conf` 或运行时凭据。
- 未修改 `inspect/`、`tests/`、`docs/`、`README.md` 实现/文档文件。
