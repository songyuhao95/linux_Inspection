# 运行手册（runbook）— 本地调试与兼容矩阵执行手册

- 文档 ID：runbook
- 适用：Linux 基础指标及 Nginx、Keepalived、Elasticsearch 中间件模块的本地调试与兼容矩阵（TD §9）执行
- 数据流（TD §2，单向）：`采集 → normalize → 原子写 JSON → 报表`；报表只消费 JSON（RR §1）
- 说明：本手册的本地/fixture 章节不连接目标主机；远程 inventory 章节只描述项目 allow-list 内的只读执行（TD §10.2/REQ-N-08）

## 1. 快速开始

```bash
bash inspect.sh --help          # 选项表（cli-contract §2）
bash inspect.sh --list-metrics  # 只读列出当前已注册指标，不采集
bash inspect.sh --info local.cpu.load_1m   # 单指标定义，不采集
```

无 `-H`/`-i` 时巡检本机（--local 语义，cli-contract §3）：

```bash
bash inspect.sh --local
```

**当前环境预期**：真实 ansible-playbook 执行需 G0 预检（ansible-core 版本 /
SSH 连接参数 / become 方式，AE §8）后显式启用；未设置 `INSPECT_FIXTURE_DIR`
时执行路径明确报 `ExecutionNotReadyError`，退出码 10（非用法错误 2），
不产生业务结论。调试/验证请使用 fixture 调试模式（§2.2）。

## 2. 本地调试（无目标主机时，TD §10）

### 2.0 Nginx 中间件（--nginx / inspect.conf）

默认巡检 = Linux 主机基础指标 + 全部已注册中间件（Nginx、Keepalived、Elasticsearch）。只巡检 Nginx：

```bash
bash inspect.sh --local --nginx          # 本机
bash inspect.sh -H inspection --nginx    # 远程 inventory 主机组
```

Nginx 进程发现只匹配真实 `nginx: master process`/`nginx: worker process` 行，使用
`[n]` 写法避免 `pgrep` 匹配承载命令的 shell。未运行且不在 `inspect.conf` 白名单 → 跳过该主机 Nginx 指标；
白名单内未运行 → CRIT「未运行」。Nginx 路径与白名单在仓库根 `inspect.conf` 配置
（格式为 `参数 = 候选值1|候选值2`）。账号密码仍放在 inventory 文件中，不放入
inspect.conf。版本基线使用 `nginx_version`；程序只从正在运行的 master 进程对应二进制
执行 `nginx -v`，版本不在允许值内为 CRIT。详见 `docs/specs/nginx-middleware.md`。

### 2.1 Keepalived 中间件（--keepalived / inspect.conf）

默认巡检也包含 Keepalived；只巡检 Keepalived 时：

```bash
bash inspect.sh --local --keepalived
bash inspect.sh -H inspection --keepalived
```

模块先从运行中的 `keepalived` 进程解析实际二进制和 `-f` 配置路径，再用根目录
`inspect.conf` 中的 `keepalived_bin`、`keepalived_conf`、`keepalived_log`、
`keepalived_vip`、`keepalived_port` 候选兜底。进程未运行且不在
`keepalived_whitelist` 的主机会跳过 Keepalived；白名单主机未运行则 CRIT。VIP 绑定、
VIP HTTP 访问、配置基线、脚本静态权限、关键日志、能力与漂移稳定性分别输出指标；
路径无法发现时输出 UNKNOWN。详细判定和复现命令见
`docs/specs/keepalived-middleware.md`。

### 2.2 Elasticsearch 中间件（--elasticsearch / inspect.conf）

只巡检 Elasticsearch：

```bash
bash inspect.sh --local --elasticsearch
bash inspect.sh -H inspection --elasticsearch
```

模块先从运行中的 Elasticsearch JVM 解析 `-Des.path.home`、`-Des.path.conf`、
`-Des.path.logs`、配置中的 HTTP/Transport 端口和证书；解析不到时按
`inspect.conf` 中的 `elasticsearch_*` 候选路径顺序兜底。未运行且不在
`elasticsearch_whitelist` 的主机跳过 ES 指标；白名单主机未运行保留进程指标并为
CRIT。API 使用目标机 `elasticsearch_auth_file` 指向的 curl netrc 文件，不把密码写入
项目配置。401/403、连接失败、路径不可读均为 UNKNOWN，不默认通过。Excel 结果写入
独立 `elasticsearch` Sheet，HTML 自动纳入中间件/指标筛选与分组。详细指标和阈值见
`docs/specs/elasticsearch-middleware.md`。

### 2.3 --local 本机自巡检

控制端兼受控端即可跑通全链路；本机命令缺失 → 对应指标 UNKNOWN，链路不断。
未设置 `INSPECT_FIXTURE_DIR` 时因真实执行未启用（§1）返回 10。

### 2.4 fixture 调试模式（实现/调试专用，非用户 CLI）

环境变量 `INSPECT_FIXTURE_DIR` 指向预录输出目录时，ansible_runner 从夹具
读取 probe 与指标原始输出（模拟受控端应答），**不产生任何连接、不执行
任何命令**；启用时 stderr 打印一行"调试模式（fixture）"声明（TD §10.2）。

```bash
INSPECT_FIXTURE_DIR=tests/fixtures/raw bash inspect.sh --local
INSPECT_FIXTURE_DIR=tests/fixtures/e2e bash inspect.sh --local
```

- 夹具布局（与 tests/fixtures/raw/ 同约定）：`<fixture_dir>/<主机名>/
  {probe.out, <metric_id>.out[, .stderr/.rc/.timeout], CONNECTION_FAILED,
  PROBE_FAILED}`；文件首部 `#` 行声明"非实测数据"并被剥离（RK-R2-06）。
- `tests/fixtures/e2e/` 为 T-108 端到端夹具（localhost 与 e2e-node-1 两主机，
  预期计数 OK=4 WARN=0 CRIT=0 UNKNOWN=6，executed=4 failed=6，见该目录
  README.txt）。
- `-H`/`-i` 与 fixture 同时出现时仍不连接任何主机（TD §10 边界）。
- 禁止把夹具数据写成"已验证的现网结论"。

### 2.5 mock inventory

`tests/fixtures/inventory/hosts.yml`（INI 格式，合成样例）用于 `-i --limit`
语义验证（不连接真实主机）：

```bash
bash inspect.sh -i tests/fixtures/inventory/hosts.yml --limit 'web*'
bash inspect.sh -i tests/fixtures/inventory/hosts.yml --all
```

`tests/fixtures/cli/hosts.yml` 为 YAML 格式样例：inventory 层只解析严格 INI
子集，YAML 文件会明确报 `inventory 解析失败`（退出码 10，不静默跳过）。

### 2.6 项目 inventory 远程调试

`inventory/hosts.ini` 是仓库内跟踪的脱敏注释模板。真实测试前，在目标控制端
复制为被忽略的 `inventory/hosts.local.ini`，取消注释并填写主机组和认证变量；真实密码
只保存在本地权限为 `600` 的文件中，不得提交或写入事件、JSON、报表和命令行。

```bash
cp inventory/hosts.ini inventory/hosts.local.ini
chmod 600 inventory/hosts.local.ini
vi inventory/hosts.local.ini
bash inspect.sh -H inspection
bash inspect.sh -H <host-or-ip-list>

# 也可以显式指定私有 inventory
bash inspect.sh -i inventory/hosts.local.ini -H inspection
```

远程模式默认关闭 Ansible 自身重复的 host-key 前置检查，并让 OpenSSH 使用
`StrictHostKeyChecking=accept-new`：首次连接自动记录指纹，已知指纹变化仍拒绝。生产环境
仍应按组织规则核验和维护 `known_hosts`。无默认 inventory 时才保留旧的环境变量兼容路径。
`--local` 不调用 Ansible；只有 `-H`/`-i` 远程模式使用项目内 Python 3.12 和 bundled Ansible。

### 2.7 单元级与 e2e

```bash
python -m pytest tests/test_render_stdout.py -q   # 解析器/渲染对夹具断言
python -m pytest tests/test_e2e.py -q             # fixture 全链路（AC-1）
python -m pytest tests/ -q                        # 全量回归（AC-2）
```

e2e（tests/test_e2e.py）以 fixture 模式驱动完整 CLI→采集→normalize→JSON→
stdout/xlsx/html 链路，并含回滚演练（TD §11，见 §4）。

## 3. 兼容矩阵 C1-C8 执行手册（TD §9）

控制端：Linux/WSL（项目 runtime 已物化且通过哈希校验，且 Linux 报表依赖已随仓库提交）；全部命令在
仓库根目录执行。`inspect.sh` 只启动 `runtime/bin/python3.12`，所有模式
都拒绝 PATH 中的系统 Python/Ansible。

| 项 | 控制端 | 受控端 | 连接凭据 | 执行命令 | 预期 | 验证方式 |
|----|--------|--------|----------|----------|------|----------|
| C1 | Linux（glibc x86_64） | 本机（--local） | — | `bash inspect.sh --local` | 退出码 0 或 20（`--fail-on critical`），事实源 JSON 生成且通过 schema | 本地可验证 |
| C2 | WSL2（Ubuntu 22.04） | 本机（--local） | — | `bash inspect.sh --local` | 同 C1 | 本地可验证 |
| C3 | WSL1 | 本机（--local） | — | `bash inspect.sh --local` | 同 C1（WSL1 内核差异处标注意外） | 本地可验证 |
| C4 | Linux/WSL2 | Kylin V10 x86_64 | SSH key + 普通账号 | `bash inspect.sh -H <ip>` | 事实源 JSON execution_status ∈ {SUCCESS,PARTIAL}；无业务伪造 | 待现场/G0 预检 |
| C5 | Linux/WSL2 | Kylin V10 | SSH + 最小化 become（sudo） | 单指标需特权场景 | 特权指标正确采集或 UNKNOWN(PERMISSION_DENIED)，其余继续 | 待现场/G0 预检 |
| C6 | Linux/WSL2 | 无 bash/无法连接主机 | — | `bash inspect.sh -H <ip>` | 单主机→退出码 10 无业务结论；多主机→PARTIAL 取最严重 | 本地可用 fixture 模拟 |
| C7 | 任意控制端 | 无目标主机 | — | `INSPECT_FIXTURE_DIR=tests/fixtures/raw bash inspect.sh --local`（调试模式） | 全链路 fixture 通过（REQ-N-08），stderr 含"调试模式（fixture）" | 本地可验证 |
| C8 | 任意控制端 | 无目标主机 | — | `python -m pytest tests/test_e2e.py -q` | 全绿 | 本地可验证 |

C4/C5 为现场/G0 预检项：控制端 Python 3 版本、ansible-core 版本、受控端
bash 版本、become 方式、SSH 连接参数均为 G0 预检范围（AE §8），本手册
不承诺版本；C6 连接失败语义以 fixture 标记文件模拟（CONNECTION_FAILED →
主机 ERROR 无业务结论；PROBE_FAILED → probe 失败 ERROR）。

## 4. 回滚演练（TD §11）

事实源 inspection_id 每次唯一（秒级精度），已写 JSON 不可变、不覆盖；
报表只读 JSON 可随时重生成（修复渲染缺陷→从同一 JSON 重渲染，不重采集）。
演练（tests/test_e2e.py 已覆盖）：

```bash
INSPECT_FIXTURE_DIR=tests/fixtures/e2e bash inspect.sh --local   # 第一次运行
sleep 1.1s                                                       # inspection_id 秒级精度
INSPECT_FIXTURE_DIR=tests/fixtures/e2e bash inspect.sh --local   # 第二次运行
```

预期：两次运行生成两个不同 inspection_id（`out/<inspection-id>/`）；旧 JSON
未被覆盖（重跑报"inspection 已存在"且不写入）；旧 inspection 目录可独立
重渲染三类报表（stdout 报告 / HTML / Excel）。

## 5. 退出码（cli-contract §4）

| 退出码 | 语义 |
|--------|------|
| 0 | 成功（含业务 WARN/CRIT 但未启用 --fail-on critical） |
| 2 | 用法错误：未知选项、参数缺失、互斥、--limit/--all 缺 -i 等 |
| 10 | 执行失败（技术）：inventory 解析失败、ExecutionNotReadyError、xlsxwriter 缺失等 |
| 20 | 业务告警：仅 --fail-on critical 且任一指标 status=CRIT |

优先级 2 > 10 > 20 > 0；Linux 项目 runtime 已内置 xlsxwriter，若仍提示缺失，先检查 runtime/site-packages 是否完整；`--excel` 明确报错退出码 10，
不中断 stdout 报表与 HTML 输出。

## 6. 输出与运行残留

- 事实源：`out/<inspection-id>/hosts/<host>.json` + `inspection-<inspection-id>-index.json`
  （`out_dir` 由 inspect.yml 配置，缺省 `out/`）；`--excel`/`--html` 无 PATH 时将
  报表写入 `Path.cwd()/<inspection-id>.xlsx|.html`，提供 PATH 时直接使用给定路径。
- 运行期临时文件：`<仓库根>/.runtime/`（临时 inventory/playbook，运行生成，
  CLI 每次运行新建随机名文件；该目录未纳入 .gitignore，调试后请清理：
  `rm -f .runtime/*` 后 `rmdir .runtime`）。
- Windows 注意：控制端中文输出经 stdout/stderr 强制 UTF-8（_reconfigure_stdio）；
  全部测试显式 utf-8 读写。
