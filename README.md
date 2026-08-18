# linux_Inspection

项目内 Linux 中间件只读巡检工具。

## 开发文档与进度事实源

后续开发、交接和进度更新以以下文件为准，优先级从上到下：

- `README.md`：当前开发状态、已完成事项、故障记录、版本信息和交接指引；
- `docs/specs/`：产品、指标、JSON、CLI、Ansible 执行和报表规格；
- `docs/reviews/`：DOCX 来源审查、冲突和未决事项；
- `docs/runbook.md`：运行方式、调试流程和安全边界；
- `docs/g0-real-vm.md`：真实 VM 测试前置条件和验证流程；
- `docs/local-vm-deploy.md`：项目部署到 VM 并执行本地巡检；
- `runtime/README.md`：项目内 Python 3.12 和 bundled Ansible runtime 约束；
- `contracts/`：任务合同、验收标准和流水线证据。

`relay.md` 已废弃，不再作为项目文档或开发状态来源。

## 当前开发状态与交接

- 已完成项目内 Python 3.12 和 bundled Ansible runtime 的强制执行路径；
- Linux x86_64/CPython 3.12 的报表依赖已随项目 runtime 提交（`pandas`、`numpy`、`xlsxwriter` 及其依赖），新 Linux 环境无需重复安装；精确版本见 `runtime/report-requirements.lock`；
- 已完成 `--local` 本地 Linux 基础指标采集，以及远程 `-H` 的统一 JSON 事实源；
- 当前远程认证以项目 inventory 为配置入口，公开模板不包含可用主机或真实凭据；
- 远程真实 VM 验证按 `docs/g0-real-vm.md` 执行，部署到 VM 按 `docs/local-vm-deploy.md` 执行；
- 新增中间件时只扩展 `inspect/modules/`，并同步更新 `docs/specs/`、测试和本 README 的交接状态。

## 执行路径

- `inspect.sh --local`：使用项目内 Python 3.12，直接调用本机 bash 探测和指标命令；**不调用 Ansible**。
- `inspect.sh -H <group-or-host>`：优先使用有效的项目内 `inventory/hosts.local.ini`，其次使用有主机的 `inventory/hosts.ini`，按主机组、主机名或 IP 选择目标，再使用项目内 Python 3.12 启动项目内打包的 Ansible；没有默认 inventory 时保留临时 inventory 兼容路径。
- `inspect.sh -i <inventory>`：使用指定 inventory 和项目内打包的 Ansible；不依赖系统 Python/Ansible。
- `INSPECT_FIXTURE_DIR=...`：两种模式都使用预录 fixture，零连接、零 Ansible。

### 报表输出

使用 `--excel [PATH]` 和 `--html [PATH]` 生成报表。省略 `PATH` 时，文件写入
当前工作目录（`Path.cwd()`）；提供 `PATH` 时直接使用给定路径。例如：

```bash
bash inspect.sh --local --excel --html
bash inspect.sh --local --excel reports/local.xlsx --html reports/local.html
```

旧参数 `--xlsx-out` 和 `--html-out` 已移除，不再被 CLI 接受。

## 监控模块扩展

监控模块注册在 `inspect/modules/`，统一通过 `MonitorModule` 和 `ModuleRegistry` 暴露指标。当前内置模块为 `linux_basic`（Linux 主机基础指标）和 `linux_common`（需要产品 profile 的通用指标）。以后新增中间件时，应：

1. 在 `inspect/metrics.py` 增加带版本/来源锚点的指标定义；
2. 在 `inspect/modules/` 增加模块文件并显式注册；
3. 在命令模板和解析器中补齐该模块所需的安全 allow-list；
4. 为模块增加 fixture 与测试。

仅把任意 `.sh`/`.py` 文件放入目录不会自动执行，必须显式注册并通过 allow-list 校验。
默认巡检只启用 `linux_basic`；未选择中间件时，`linux_common` 不进入执行计划，
因此不会生成 `UNSUPPORTED_PROFILE` 的 UNKNOWN 指标。后续中间件适配器接入后，
由编排层显式选择对应模块。

### Linux 主机基础指标

`inspect/modules/linux_basic.py` 是独立的 profile-free 基础模块，当前采集并进入
`out/<inspection_id>/hosts/<host>.json` 事实源的指标包括：

- `local.filesystem.used_percent`：所有文件系统挂载点的磁盘使用率；JSON `evidence.details` 保存 `filesystem`、`mount`、`used_percent` 和挂载点级 `status` 明细，终端逐挂载点显示独立状态；`normalized_value` 仍为所有挂载点中的最大值；
- `local.filesystem.inode_used_percent`：所有文件系统挂载点的 inode 使用率，结构与磁盘使用率相同；挂载点级状态与指标整体状态分别保存，整体状态仍按最大使用率聚合；
- `local.memory.available_percent`：可用内存百分比；
- `local.cpu.utilization`：`top -bn2 -d 1` 的一秒窗口 CPU 使用率；
- `local.cpu.load_1m`：从同一份 `/proc/loadavg` 事实读取 1 分钟、5 分钟、15 分钟系统负载，并与 CPU 核数比较；stdout 逐行显示“1 分钟系统负载：值（1分钟，CPU核数=N，负载/核数=实际比值，阈值<=1.00，正常）”，括号内容来自 JSON `evidence.details`；metric 级兼容值仍为 1 分钟负载；
- `local.swap.used_percent`：Swap 使用率。

这组指标不依赖中间件 profile，在 `--local` 和远程 `-H/--hosts` 模式都复用同一套
命令模板、解析器、状态判定和 `host-result-v1` JSON 事实源。报表只读消费这些 JSON，
不会再次采集。

## 终端指标输出

终端报表读取已经落盘的 `host-result-v1` JSON，在每台主机摘要后输出已执行指标的
中文字段名、状态、规范化值和单位，例如 `CPU 使用率: 12.34 %` 或 `1 分钟系统负载：0.52（1分钟，CPU核数=8，负载/核数=0.07，阈值<=1.00，正常）`。失败或未选择的
指标不伪造数值，仍在失败/未知列表中展示原因。

## 远程主机配置

项目跟踪的 `inventory/hosts.ini` 是**仅含注释的脱敏模板**，用于演示主机组、
`ansible_host`、`ansible_user` 和 `ansible_password` 的写法。模板中的示例 IP 使用
TEST-NET 地址，密码是占位符，不可直接用于连接。

实际部署建议复制为本地私有 inventory，取消注释并替换为现场配置：

```bash
cp inventory/hosts.ini inventory/hosts.local.ini
chmod 600 inventory/hosts.local.ini
vi inventory/hosts.local.ini
```

默认 `-H` 会自动优先使用有效的 `inventory/hosts.local.ini`。如果直接编辑跟踪的
`inventory/hosts.ini`，检查后不要提交包含真实凭据的修改。也可以复制成其他私有
inventory，通过 `-i` 显式指定：

```bash
cp inventory/hosts.ini inventory/hosts.local.ini
chmod 600 inventory/hosts.local.ini
vi inventory/hosts.local.ini
bash inspect.sh -H inspection
```

`inventory/hosts.local.ini` 等本地变体被 `.gitignore` 忽略。默认 inventory 配置完成后，
远程巡检不需要每次设置 `INSPECT_REMOTE_USER` 或 `INSPECT_ASK_PASS`，可以直接使用主机组、
主机名或 IP：

```bash
bash inspect.sh -H inspection
bash inspect.sh -H node-01,node-02
bash inspect.sh -H <host-or-ip-list>
```

`-H` 会复用项目内 inventory，认证变量由项目内 bundled Ansible 原生读取；解析器只读取
主机名和 `ansible_host` 作为报告元数据，不会把认证变量写入 JSON、事件或报表。远程模式
默认使用 `ANSIBLE_HOST_KEY_CHECKING=False` 配合 OpenSSH
`StrictHostKeyChecking=accept-new`：首次连接会记录主机指纹，已知指纹发生变化仍会拒绝；
生产环境仍建议按组织规则预先核验并管理 `known_hosts`。

`--local` 是本地排查模式，不经过 Ansible；只有远程 `-H` 或 `-i` 模式才调用项目内 bundled Ansible。
