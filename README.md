# linux_Inspection

项目内 Linux 中间件只读巡检工具。

## 执行路径

- `inspect.sh --local`：使用项目内 Python 3.12，直接调用本机 bash 探测和指标命令；**不调用 Ansible**。
- `inspect.sh -H <group-or-host>`：优先使用项目内 `inventory/hosts.ini`，按主机组、主机名或 IP 选择目标，再使用项目内 Python 3.12 启动项目内打包的 Ansible；没有默认 inventory 时保留临时 inventory 兼容路径。
- `inspect.sh -i <inventory>`：使用指定 inventory 和项目内打包的 Ansible；不依赖系统 Python/Ansible。
- `INSPECT_FIXTURE_DIR=...`：两种模式都使用预录 fixture，零连接、零 Ansible。

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

- `local.filesystem.used_percent`：根文件系统 `/` 磁盘使用率；
- `local.filesystem.inode_used_percent`：根文件系统 `/` inode 使用率；
- `local.memory.available_percent`：可用内存百分比；
- `local.cpu.utilization`：`top -bn2 -d 1` 的一秒窗口 CPU 使用率；
- `local.cpu.load_1m`：1 分钟系统负载与 CPU 核数；
- `local.swap.used_percent`：Swap 使用率。

这组指标不依赖中间件 profile，在 `--local` 和远程 `-H/--hosts` 模式都复用同一套
命令模板、解析器、状态判定和 `host-result-v1` JSON 事实源。报表只读消费这些 JSON，
不会再次采集。

## 终端指标输出

终端报表读取已经落盘的 `host-result-v1` JSON，在每台主机摘要后输出已执行指标的
中文字段名、状态、规范化值和单位，例如 `CPU 使用率: 12.34 %`。失败或未选择的
指标不伪造数值，仍在失败/未知列表中展示原因。

## 远程主机配置

远程巡检不需要每次设置 `INSPECT_REMOTE_USER` 或 `INSPECT_ASK_PASS`。复制
`inventory/hosts.ini.example` 为 `inventory/hosts.ini`，在其中配置主机组、
`ansible_user` 和 `ansible_password`：

```bash
cp inventory/hosts.ini.example inventory/hosts.ini
chmod 600 inventory/hosts.ini
# 编辑 inventory/hosts.ini，替换 REPLACE_WITH_REAL_PASSWORD
```

`inventory/hosts.ini` 已加入 `.gitignore`，真实密码不会进入 Git。执行时可直接使用
主机组或 IP，`-H` 会复用该 inventory，认证变量由项目内 Ansible 原生读取：

```bash
bash inspect.sh -H inspection
bash inspect.sh -H 192.0.2.10,192.0.2.11
```

`-i <inventory>` 仍可用于指定其他 inventory。inventory 解析器只读取主机名和
`ansible_host` 作为报告元数据，不会把认证变量写入 JSON、事件或报表。
