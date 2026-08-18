# G0 两台虚拟机只读验证与使用说明

## 1. 适用范围

本说明用于在控制端 WSL/Linux 上，对已明确授权的两台虚拟机执行只读基础巡检：

- `node01`：`192.168.0.10`
- `kylin01`：`192.168.0.101`
- 远程账号和认证：由项目 `inventory/hosts.ini` 的本地配置提供

除上述两台主机外，不应把本说明中的真实执行门禁用于其他地址。该路径只执行项目 allow-list 中的只读命令，不执行安装、删除、停止服务、写入配置或修改业务数据的操作。

## 2. 控制端前置条件

建议从 WSL2/Linux 控制端、仓库根目录执行。真实执行不从 PATH 查找
Python 或 `ansible-playbook`，而是要求已经部署并校验的项目 runtime：

```bash
runtime/bin/python3.12 -VV
PYTHONNOUSERSITE=1 PYTHONPATH=runtime/ansible/site-packages \
  runtime/bin/python3.12 -c 'import ansible, ansible.cli.playbook; print(ansible.__file__)'
```

首次使用前应确认：

1. `runtime/manifest.json` 为 `status=built`，Python/Ansible 哈希已校验；
2. 项目 runtime 中的 `ansible.cli.playbook` 能由 `runtime/bin/python3.12` 导入；
3. 控制端可以通过 SSH 访问两台主机；
4. 账号具备只读命令权限；
5. 初次 smoke 不启用 `become`；
6. 目标端具备 `/bin/bash` 和探测所需命令；
7. 目标主机指纹已按组织规则确认；runner 只对 Ansible 前置检查使用
   `ANSIBLE_HOST_KEY_CHECKING=False`，底层 OpenSSH 仍使用 `StrictHostKeyChecking=accept-new`，
   已知指纹变化会拒绝连接。

真实路径必须从 WSL/Linux 控制端运行；代码中的 `INSPECT_ALLOW_WINDOWS_REAL=1` 仅供合成单元测试，不能用于现场绕过该门禁。

对于“在 VM 自身运行脚本”的单独部署流程，不使用 Windows/WSL 作为 Ansible 控制端。每台 VM 先部署到 `/data/inspect`，确认项目内 `runtime/bin/python3.12` 与 bundled Ansible 已通过哈希和导入校验，然后以本机作为控制端运行 `--local`。不得安装或选择系统 Ansible；该流程需要额外的 `INSPECT_ENABLE_LOCAL_REAL=1` 门禁，详见 [local-vm-deploy.md](local-vm-deploy.md)。

真实远程分支使用项目 runtime 和有效的本地 inventory（优先 `inventory/hosts.local.ini`，其次 `inventory/hosts.ini`）；远程分支仍会拒绝未授权目标。本机 `--local` 分支不经过远程 Ansible，只接受生成的 `localhost ansible_connection=local` inventory；它不接受远程账号或 `INSPECT_ASK_PASS`。

## 3. 凭据安全

仓库中的 `inventory/hosts.ini` 只保留注释形式的脱敏示例。真实测试时，在控制端复制为被忽略的 `inventory/hosts.local.ini`，取消注释并填写现场
主机、账号和认证变量，文件权限应为 `600`。真实 inventory 不得提交到 Git。

```bash
cp inventory/hosts.ini inventory/hosts.local.ini
chmod 600 inventory/hosts.local.ini
vi inventory/hosts.local.ini
# 默认 inventory 配置完成后直接按组或 IP 执行
bash inspect.sh -H inspection
```

密码只由项目内 bundled Ansible 从本地 inventory 原生读取，不进入命令行、环境快照、
JSON、HTML、事件或聊天输出。不要设置 `ANSIBLE_PASSWORD`、`SSHPASS`，不要把密码拼接
到 shell 命令中。若使用 SSH key/agent，可不配置密码变量。

如果没有默认 inventory，旧的 `INSPECT_REMOTE_USER`/`INSPECT_ASK_PASS` 兼容路径仍可用，
但优先使用项目 inventory，避免每次执行前设置环境变量。

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

真实模式必须满足项目 runtime 校验和目标授权；默认认证来源是项目 inventory。只有在没有默认 inventory、需要兼容旧临时 inventory 路径时，才使用 `INSPECT_REMOTE_USER`，密码提示另加 `INSPECT_ASK_PASS=1`。未满足真实执行门禁时，程序返回 10 并明确说明真实 Ansible 未启用；这不是成功的 VM 测试。

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
- 项目 runtime 缺失、Python/Ansible 导入失败或 callback 不是结构化 JSON；
- 目标范围不能证明只有两台授权主机；
- 需要关闭 host-key 检查、写入密码文件或把密码放入 argv；
- 生成命令出现写操作、网络探测、安装、删除或服务变更；
- 目标 bash、SSH、账号权限或 become 行为未确认；
- callback 原始输出会被写入报告、事件日志或 Git。

验证报告只记录主机标签、时间、版本、退出码、状态计数和失败类别，不记录密码、密钥、原始 SSH 命令、原始 callback 或未脱敏日志。

## T-110: bundled Ansible is mandatory

The real-runner gate now treats Ansible as part of the project runtime, not as
an operating-system dependency. The deployable runtime must contain:

```text
runtime/bin/python3.12
runtime/ansible/site-packages/ansible/
runtime/ansible/collections/
```

Execution is forced through the dedicated interpreter and module entry point:
`runtime/bin/python3.12 -m ansible.cli.playbook`. The resolver and child
environment reject system Ansible, inherited Python paths, user-site imports,
and out-of-tree package resolution. Missing or invalid bundles fail closed
with technical exit code 10.

The checked-in manifest records the materialized Linux x86_64 runtime as
`status=built`, including the Python and bundled Ansible hashes. This proves
only that the deployable artifact was built; it is not evidence of a successful
VM/SSH or local inspection run. Verify the artifact on each target before
claiming VM execution.
