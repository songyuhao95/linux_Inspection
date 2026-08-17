# G0 两台虚拟机只读验证报告

- 日期：2026-08-16
- 目标范围：`node01`（`192.168.0.10`）、`kylin01`（`192.168.0.101`）
- 账号：仅记录为受控远程账号变量，不记录账号凭据或密码
- 结论：**未完成真实 VM 连接；按停止条件阻断**

## 1. 已完成的本地验证

| 项目 | 结果 | 证据/说明 |
|---|---|---|
| Python 语法检查 | 通过 | `python -m py_compile inspect/ansible_runner.py inspect/cli.py tests/test_g0_remote_runner.py` |
| 真实 runner 模拟测试 | 通过 | `tests/test_g0_remote_runner.py` 与 `tests/test_ansible_runner.py` 全部通过 |
| 全量 pytest | 通过 | `python -m pytest tests/ -q`，无失败；既有依赖缺失相关用例按测试标记跳过 |
| fixture 端到端 | 通过 | `INSPECT_FIXTURE_DIR=tests/fixtures/e2e bash inspect.sh --local --html`；零连接、JSON 与 HTML 生成成功 |
| 目标范围门禁 | 已实现并有测试 | 真实路径只接受两个授权 IP；其他地址在调用 Ansible 前拒绝 |
| 凭据门禁 | 已实现并有测试 | 真实路径要求显式远程账号；密码只允许 Ansible `--ask-pass` 交互输入，不进入 argv/结果 |
| 运行期清理 | 已实现并有测试 | 真实路径在成功、解析失败或控制端异常后清理本次生成的临时文件 |

本地 fixture 输出只使用合成预录数据，不代表任何 VM 的实测结果。

## 2. G0 控制端阻断

当前会话运行在 Windows Git Bash，而不是已确认可用的 WSL/Linux 控制端。当前 shell 中：

- Python：可用（3.12.10）；
- `ansible-playbook`：不可用；
- Python `ansible` 模块：不可用；
- `xlsxwriter`：不可用（未自动安装）；
- WSL 发行版：当前工具环境未提供可用发行版入口。

依据停止条件，未执行任何 SSH、Ansible、端口探测、远程命令或密码输入，也未声称两台 VM 已测试成功。不得使用仅供合成测试的 `INSPECT_ALLOW_WINDOWS_REAL=1` 绕过 WSL/Linux 门禁。

## 3. 待现场执行的安全步骤

在已审核的 WSL/Linux 控制端，或按单独授权在 VM 自身部署后，确认 `ansible-playbook` 与 SSH host key/传输条件，再按 [docs/g0-real-vm.md](../../docs/g0-real-vm.md) 或 [docs/local-vm-deploy.md](../../docs/local-vm-deploy.md) 逐台执行。不得写密码文件、使用 `sshpass` 或把密码放入命令行。

真实验证完成后，另行补充两台主机的脱敏退出码、`SUCCESS/PARTIAL/ERROR` 计数、`OK/WARN/CRIT/UNKNOWN` 计数和失败类别。不得把原始 callback、SSH 诊断、日志或凭据写入本报告。

## 4. 直接 VM 本地执行尝试（2026-08-16）

本次按用户新增的 `/data/inspect` 本地执行方案进行了定向 SSH 前置检查，但未进入部署、Ansible 安装或巡检命令：

| 主机 | 结果 | 脱敏失败类别 |
|---|---|---|
| `node01`（`192.168.0.10`） | 阻断 | `HOST_KEY_UNCONFIRMED` |
| `kylin01`（`192.168.0.101`） | 阻断 | `AUTHENTICATION_UNAVAILABLE` |

未向任一 VM 写入 `/data/inspect`，未安装 Ansible，未执行远程或本地巡检，也未输入或保存密码。`node01` 尚未完成组织确认的 host key 校验；`kylin01` 当前没有可用的已审核非交互 SSH key/agent。当前工具没有可安全承载一次性 SSH 密码交互的 TTY，因此不能用密码参数、环境变量或 `sshpass` 绕过该阻断。

恢复条件：先由管理员在安全终端确认 `node01` 的 host key，并为两台 VM 提供已审核 SSH key/agent 或可交互 TTY；随后才能按 [docs/local-vm-deploy.md](../../docs/local-vm-deploy.md) 逐台部署和执行。该阻断不代表两台 VM 的巡检成功或失败结果。
