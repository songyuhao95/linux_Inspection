# 两台 VM 本地部署与只读验证说明

## 范围

本说明只适用于已经明确授权的两台麒麟/Linux VM：

- `node01`：`192.168.0.10`
- `kylin01`：`192.168.0.101`

脚本部署目录固定为 `/data/inspect`。本流程不是从 Windows Git Bash 或本地 WSL 运行 Ansible；每台 VM 都作为自己的 Ansible 控制端，在本机执行 `--local`。

## 部署边界

部署与安装是单独授权的目标机操作。只允许：

1. 将 `inspect.sh`、完整 `inspect/` 包和已经哈希校验的 `runtime/` 部署到 `/data/inspect`；
2. 只运行项目内的 `runtime/bin/python3.12` 与 bundled `runtime/ansible/`，不安装或选择目标机系统 Ansible；
3. 写入巡检自身生成的 `/data/inspect/.runtime` 和 `/data/inspect/out`。

不得添加第三方软件源，不得使用 `pip`、下载脚本、`curl | bash` 或 `sshpass`。本地 `--local` 巡检不需要远程密码、密码环境变量或远程 inventory；控制端执行远程 `-H` 时，认证配置另见 `docs/g0-real-vm.md`，真实 inventory 不随部署包提交。部署前保留旧版本和校验清单；部署失败时恢复旧版本。

## 认证与传输

从控制端向 VM 传输时优先使用已审核的 SSH key/agent。密码只能在安全的交互式 SSH/SCP 提示中输入；不能把密码放在命令、脚本、环境变量或部署包中。若当前控制端没有安全交互 TTY 且没有可用 key/agent，应停止传输并记录阻断，不要请求密码进入聊天或改用 `sshpass`。

部署包不得包含 `.git/`、`.runtime/`、`out/`、缓存、测试真实输出、inventory 凭据、密钥或报告中的敏感内容。部署前记录源文件清单和哈希，VM 上校验后再激活到 `/data/inspect`。

## VM 前置检查

在每台授权 VM 上分别执行只读检查，确认项目 runtime 已部署并可执行：

```bash
runtime/bin/python3.12 -VV
PYTHONNOUSERSITE=1 PYTHONPATH=runtime/ansible/site-packages \
  runtime/bin/python3.12 -c 'import ansible, ansible.cli.playbook; print(ansible.__file__)'
test -d runtime/ansible/collections
```

还需确认目标端具有 `/bin/bash`、`timeout` 以及共同指标使用的探测命令。若项目 runtime 缺失、哈希不匹配或导入路径越界，先停止并修复部署物，不得改用系统 Python/Ansible。

## 本地真实门禁

fixture 模式仍然优先且零连接。真实本地模式必须同时设置两个门控变量：

```bash
# inspect.sh automatically sets these non-secret local flags in its child only.
# It also rejects a missing/mismatched project-local Python 3.12 runtime.
```

`--local` 生成的 inventory 必须精确包含：

```ini
[all]
localhost ansible_connection=local
```

本地模式不需要 SSH 用户或密码，Ansible 使用 `stdin` 关闭的 credentialless local transport。`INSPECT_ENABLE_LOCAL_REAL=1` 不会扩大远程 `-H` 目标范围；远程控制端的主机组和认证配置使用项目 inventory，具体见 `docs/g0-real-vm.md`。

## 执行顺序

每台 VM 独立执行，先 `node01`，后 `kylin01`。先确认生成的 playbook 仍为 `gather_facts: false`、`serial: 1`、`raw`、`/bin/bash -lc`、只读 allow-list、无重试；首轮不依赖需要确认 sudo 策略的端口和日志 profile。

```bash
cd /data/inspect
# inspect.sh automatically sets these non-secret local flags in its child only.
# It also rejects a missing/mismatched project-local Python 3.12 runtime.
bash inspect.sh --local --html out/local-smoke.html
```

确认 JSON 事实源、stdout 和离线 HTML 已生成。项目 Python 运行时应先安装 requirements.txt 中的 `pandas` 与 `xlsxwriter`，再执行 Excel：

```bash
bash inspect.sh --local --excel out/local-smoke.xlsx
```

本地执行中：

- 主机连接不涉及 SSH；Ansible 的 `ansible_connection=local` 直接调用本机；
- 单指标权限不足、超时和缺命令是 `UNKNOWN`，其余指标继续；
- 控制端或能力探测失败是主机 `ERROR`，不产生业务结论；
- 业务 `OK/WARN/CRIT/UNKNOWN` 与主机 `SUCCESS/PARTIAL/ERROR` 分离；
- 技术失败退出码为 `10`，不能伪装成业务 `CRIT`。

运行第二次时必须产生新的 `inspection_id`，旧 JSON 不覆盖且可以独立重新渲染。验证完成后删除本次 `.runtime` 临时 inventory、playbook 和 callback 运行材料；保留经检查的事实源和脱敏报告。

## 证据与停止条件

报告只记录 VM 标签、授权 IP、执行时间、源清单哈希、Python/Ansible 版本、退出码、执行状态计数、指标状态计数、耗时和脱敏错误类别。不得记录密码、密钥、原始 SSH 诊断、原始 callback、原始命令输出或未脱敏日志。

以下任一情况停止：Ansible 无法从已配置原生仓库安装、root/sudo 不可用、无法安全传输、生成命令不是只读、local inventory 不是精确 `localhost ansible_connection=local`、结构化 callback 不可用、出现未批准目标或需要写入业务配置。

## T-110 project-local Ansible requirement

The local VM deployment path must ship the complete `inspect/` tree together
with `runtime/bin/python3.12` and `runtime/ansible/`. It must not install or
select Ansible from the target VM's system package set. `inspect/runtime.py`
validates the manifest, Python 3.12, the bundled `ansible.cli.playbook` module,
and the in-tree collection path before real execution. `inspect/ansible_runner.py`
then launches Ansible only as:

```text
runtime/bin/python3.12 -m ansible.cli.playbook ...
```

The child environment removes inherited `PYTHONPATH`, `PYTHONHOME`, virtualenv,
Ansible configuration/plugin/collection paths, and user-site imports before
adding the project-owned Ansible site-packages path. If the bundle is absent,
invalid, or resolves outside `runtime/`, inspection returns technical failure
(code 10); it never falls back to `ansible-playbook` from `PATH`.

The checked-in `runtime/manifest.json` identifies the materialized Linux x86_64
runtime (`status=built`) and records the Python and bundled Ansible hashes. A
source checkout with `status=not-built` is not deployable; materialize an
approved archive with `tools/build-runtime.sh` before transfer. Never hand-edit
the manifest to claim a runtime that has not been verified.
