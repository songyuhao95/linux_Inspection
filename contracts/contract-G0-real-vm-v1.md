```json
{
  "contract_id": "contract-G0-real-vm-v1",
  "contract_version": 1,
  "contract_sha256": "sha256:pending-local-seal",
  "run_id": "run-20260814-001",
  "phase": "g0-validation",
  "manual_gate_required": true,
  "network_scope": ["192.168.0.10", "192.168.0.101"],
  "objective": "在已审核的 WSL/Linux 控制端对两台明确授权的麒麟/Linux VM 执行只读 Ansible smoke，产出脱敏事实源和验证报告；控制端不具备前置条件时停止。",
  "owned_paths": [
    "inspect/ansible_runner.py",
    "inspect/cli.py",
    "tests/test_ansible_runner.py",
    "tests/test_g0_remote_runner.py",
    "docs/g0-real-vm.md",
    "run/reports/G0-real-vm.md"
  ],
  "forbidden_ops": [
    "install_dependencies",
    "write_target",
    "delete_target",
    "stop_service",
    "modify_config",
    "network_discovery",
    "secret_access",
    "write_password_file",
    "password_in_argv",
    "commit",
    "push"
  ],
  "acceptance": [
    "默认无 fixture 且无 INSPECT_ENABLE_REAL 时返回执行失败 10，不连接主机",
    "真实路径只允许两个授权 IP、显式远程账号、WSL/Linux 控制端和结构化 JSON callback",
    "gather_facts=false、serial=1、raw + /bin/bash -lc、只读 allow-list、无重试",
    "连接/探测失败为主机 ERROR，单指标权限/超时/缺命令为 UNKNOWN 并继续",
    "密码只能由 Ansible --ask-pass 交互读取，不进入 argv、inventory、报告或日志",
    "本地模拟测试、fixture e2e、全量 pytest 和静态安全检查通过",
    "实际 VM 验证必须在 WSL/Linux 前置条件满足后单主机再双主机执行；无法满足即记录阻断"
  ],
  "input_artifacts": [
    {
      "path": "C:/Users/SYH/.claude/plans/linux-docx-execl-html-1-ps-jaunty-ripple.md",
      "sha256": "0b1e5ccc41ef95153b6f6db0412baefdcfd8855858df8fecdc7a124eb581b071"
    },
    {
      "path": "docs/specs/ansible-execution.md",
      "version": "G1-approved"
    },
    {
      "path": "docs/specs/host-result-v1.md",
      "version": "G1-approved"
    }
  ],
  "status": "sealed-local-addendum"
}
```

# G0 两台 VM 只读验证合同 v1

## 边界

本合同只覆盖 `node01`（`192.168.0.10`）和 `kylin01`（`192.168.0.101`）的只读验证。受控端不要求 Python；控制端必须是已审核的 WSL/Linux，并使用 Ansible transport。除授权地址外的真实目标一律拒绝。

## 凭据

远程账号通过 `INSPECT_REMOTE_USER` 传入。密码不写入任何文件、环境快照、命令行、inventory、报告、JSON、HTML、Git 或聊天；一次性密码只能在交互式 `--ask-pass` 提示中输入。非 TTY 环境安全停止。

## 停止规则

`ansible-playbook` 不可用、WSL/Linux 不可用、host key/SSH 行为未确认、结构化 callback 不可用、目标范围不能证明精确匹配、命令不是只读、需要写入密码文件或需要未经确认的 become 时，不执行任何连接并记录阻断。

## 交付

本合同不授权安装依赖、提交、推送或修改目标 VM。真实成功与否以脱敏的 [run/reports/G0-real-vm.md](../run/reports/G0-real-vm.md) 为准；本地 fixture 或模拟 callback 结果不得冒充 VM 实测。
