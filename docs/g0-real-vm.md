# G0 两台虚拟机只读验证与使用说明

## 1. 适用范围

本说明用于在控制端 WSL/Linux 上，对已明确授权的两台虚拟机执行只读基础巡检：

- `node01`：`192.168.0.10`
- `kylin01`：`192.168.0.101`
- 远程账号：通过 `INSPECT_REMOTE_USER` 指定

除上述两台主机外，不应把本说明中的真实执行门禁用于其他地址。该路径只执行项目 allow-list 中的只读命令，不执行安装、删除、停止服务、写入配置或修改业务数据的操作。

## 2. 控制端前置条件

建议从 WSL2/Linux 控制端、仓库根目录执行。真实执行不会自动安装依赖：

```bash
python3 --version
ansible-playbook --version
```

首次使用前应确认：

1. `ansible-playbook` 来自已审核的 ansible-core 环境；
2. 控制端可以通过 SSH 访问两台主机；
3. 账号具备只读命令权限；
4. 初次 smoke 不启用 `become`；
5. 目标端具备 `/bin/bash` 和探测所需命令；
6. 目标主机指纹已按组织规则确认；不应为了绕过提示而盲目关闭 host-key 检查。

真实路径必须从 WSL/Linux 控制端运行；代码中的 `INSPECT_ALLOW_WINDOWS_REAL=1` 仅供合成单元测试，不能用于现场绕过该门禁。

对于“在 VM 自身运行脚本”的单独部署流程，不使用 Windows/WSL 作为 Ansible 控制端。每台 VM 先部署到 `/data/inspect`，确认或按单独授权从其已配置原生仓库安装 `ansible-core`，然后以本机作为控制端运行 `--local`。该流程需要额外的 `INSPECT_ENABLE_LOCAL_REAL=1` 门禁，详见 [local-vm-deploy.md](local-vm-deploy.md)。

只有明确设置 `INSPECT_ENABLE_REAL=1` 才会进入真实 Ansible 分支；远程分支还会拒绝非 `192.168.0.10` / `192.168.0.101` 的目标，并要求显式设置远程账号。本机 local 分支必须同时设置 `INSPECT_ENABLE_LOCAL_REAL=1`，且只接受生成的 `localhost ansible_connection=local` inventory；它不接受远程账号或 `INSPECT_ASK_PASS`。

## 3. 凭据安全

密码不写入 inventory、命令行、环境快照、代码、报告、JSON、HTML、Git 或聊天输出。

一次性密码验证使用 Ansible 的交互式提示：

```bash
export INSPECT_ENABLE_REAL=1
export INSPECT_REMOTE_USER=aqwh
export INSPECT_ASK_PASS=1
```

随后执行巡检，Ansible 会在终端提示输入密码。不要设置 `ANSIBLE_PASSWORD`、`SSHPASS`，不要把密码放入 `hosts.ini`，也不要使用 shell 命令拼接密码。若当前终端不是可交互 TTY，程序会在连接前安全退出，而不是尝试把密码写入临时文件或命令参数。

更适合长期使用的方式是 SSH agent/密钥认证：不设置 `INSPECT_ASK_PASS`，由 Ansible 使用已审核的 SSH transport 配置。密钥路径和 sudo/become 策略由控制端配置管理，不写入巡检结果。

真实路径还会拒绝未设置 `INSPECT_REMOTE_USER` 的调用；建议验证结束后清除门控变量：

```bash
unset INSPECT_ENABLE_REAL INSPECT_REMOTE_USER INSPECT_ASK_PASS
```

## 4. 推荐执行顺序

### 4.1 先做静态与控制端检查

```bash
bash inspect.sh --help
bash inspect.sh --list-metrics
bash inspect.sh --info local.cpu.load_1m
```

确认生成的 playbook 使用 `gather_facts: false`、`serial: 1`、`raw` 与 `/bin/bash -lc`，并且目标范围只有本次授权的两台主机。真实 smoke 初期建议只启用无 profile、无 become 的共同指标；端口和日志指标需要额外的权限与路径确认。

### 4.2 单主机 smoke

```bash
bash inspect.sh -H 192.168.0.10
bash inspect.sh -H 192.168.0.101
```

使用密码时，每条命令均在 Ansible 提示时手工输入，不要把密码追加到命令末尾。先单主机验证 SSH、bash、探测 callback 和 JSON 落盘，再进行双主机运行。

### 4.3 双主机运行

```bash
bash inspect.sh -H 192.168.0.10,192.168.0.101
```

执行顺序固定为 `serial: 1`。连接失败属于技术执行失败，不能伪装为业务 `CRIT`；单指标权限不足会记录为 `UNKNOWN` 并继续其他指标。

### 4.4 报表

```bash
bash inspect.sh -H 192.168.0.10,192.168.0.101 --html
bash inspect.sh -H 192.168.0.10,192.168.0.101 --excel
bash inspect.sh -H 192.168.0.10,192.168.0.101 --excel --html \
  --xlsx-out out/vm-check.xlsx --html-out out/vm-check.html
```

Excel 依赖 `xlsxwriter`。程序不会自动安装依赖；若缺少该依赖，JSON/stdout/HTML 仍按既有编排执行，Excel 项报告技术失败并使用退出码 10 语义。

## 5. 输出与回滚

默认事实源和报表位于：

```text
out/<inspection-id>/hosts/<host>.json
out/<inspection-id>/inspection-<inspection-id>-index.json
out/<inspection-id>.xlsx
out/<inspection-id>.html
```

JSON 是唯一事实源。stdout、Excel、HTML 只消费已落盘 JSON，不重新连接主机、不重新采集。每次运行产生新的 `inspection_id`，旧 JSON 不覆盖；旧 JSON 可以独立重新渲染。

临时 playbook 和 inventory 位于 `.runtime/`，验证完成后确认其中没有凭据或原始敏感输出，再清理临时文件。不要把 `.runtime/`、真实 inventory、Ansible callback 原始输出或真实日志提交到 Git。

## 6. 退出码

| 退出码 | 含义 |
|---:|---|
| 0 | 执行完成；默认不因业务 WARN/CRIT 失败 |
| 2 | CLI 用法错误、未知参数、主机选择冲突 |
| 10 | 控制端/Ansible/SSH/探测/事实源/报表技术失败 |
| 20 | 使用 `--fail-on critical` 且存在业务 `CRIT` |

`--fail-on` 推荐完整写法：

```bash
bash inspect.sh -H 192.168.0.10,192.168.0.101 --fail-on critical
```

技术失败优先于业务告警：如果连接失败，即使其他主机或指标存在 `CRIT`，仍返回 10。

## 7. fixture 与真实模式的区别

fixture 模式只读取预录文件，不连接任何主机：

```bash
INSPECT_FIXTURE_DIR=tests/fixtures/e2e bash inspect.sh --local
```

真实模式必须同时满足：

```bash
INSPECT_ENABLE_REAL=1
INSPECT_REMOTE_USER=<受控账号>
```

密码认证另加 `INSPECT_ASK_PASS=1`，只在交互终端中输入。未设置真实执行门禁时，程序返回 10 并明确说明真实 `ansible-playbook` 未启用；这不是成功的 VM 测试。

## 8. UNKNOWN 与故障判读

- `execution_status=ERROR`：主机连接、bash/探测或控制端技术故障，没有业务结论；
- `execution_status=PARTIAL`：主机已执行，但一个或多个指标失败；失败指标为 `UNKNOWN`；
- `PERMISSION_DENIED`：单指标权限不足，继续其他指标；
- `TIMEOUT`：单指标达到任务超时，继续其他指标；
- `COMMAND_NOT_FOUND`：能力探测未发现所需命令，指标为 `UNKNOWN`；
- `CRIT`：只表示业务阈值判定，不表示 SSH 或 Ansible 连接失败。

## 9. 停止条件

出现以下任一情况应停止真实连接并记录为未完成：

- 控制端不是已审核的 WSL/Linux 环境；
- `ansible-playbook` 不存在或 callback 不是结构化 JSON；
- 目标范围不能证明只有两台授权主机；
- 需要关闭 host-key 检查、写入密码文件或把密码放入 argv；
- 生成命令出现写操作、网络探测、安装、删除或服务变更；
- 目标 bash、SSH、账号权限或 become 行为未确认；
- callback 原始输出会被写入报告、事件日志或 Git。

验证报告只记录主机标签、时间、版本、退出码、状态计数和失败类别，不记录密码、密钥、原始 SSH 命令、原始 callback 或未脱敏日志。
