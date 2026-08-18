"""inspect/probe.py — 能力探测命令集合与解析（T-103）。

职责（docs/specs/technical-design.md §4 probe.py 行 + §5.1，AE §3）：
  - 每台受控主机执行采集前先探测命令可用性：`/bin/bash -lc` 包裹
    `command -v bash; command -v pgrep; ...`（TD §5.1 逐字命令），超时 15s；
  - 输出逐行解析为能力矩阵（{命令: 可用/缺失}）：`command -v X` 成功输出
    绝对路径 → available；无输出/非零 → missing（TD §5.1 解析规则）；
  - bash 本身不可用 → 该主机整体 execution_status=ERROR，不产生业务结论；
    其余命令缺失 → 相关指标 UNKNOWN（error=COMMAND_NOT_FOUND）并继续
    （AE §3）；
  - 指标 → 所需命令映射（TD §5.2 数据源列只读转写）：ansible_runner
    以此判定某指标因命令缺失而 UNKNOWN（AE §3），本模块只提供数据与解析，
    不做执行、不做业务判定。

模块边界（TD §4）：probe.py 无包内依赖（零出边）；不执行任何命令、
不发起连接（命令文本由 ansible_runner 封装进 playbook 执行）；
"探测之外的命令执行"为禁止行为（TD §4 probe.py 行）。

探测命令集合与超时属冻结设计（TD §5.1/AE §7）：probe 15s；
指标命令 10s（日志类 15s）；单主机总时长 300s（均见 ansible_runner）。
"""

from __future__ import annotations

from typing import Dict, Tuple

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

# TD §5.1 / AE §7：能力探测超时 15s
PROBE_TIMEOUT_SEC = 15

# TD §5.1 能力探测命令集合（逐字转写；命令顺序即输出行顺序）
PROBE_COMMANDS = (
    "bash",
    "pgrep",
    "ps",
    "ss",
    "free",
    "df",
    "top",
    "systemctl",
    "tail",
    "grep",
    "nproc",
)

# 探测结果取值
AVAILABLE = "available"
MISSING = "missing"

# 探测整体状态（AE §3：bash 不可用 → 主机整体 ERROR）
PROBE_OK = "ok"
PROBE_FAILED = "failed"

# --------------------------------------------------------------------------
# 探测命令构造
# --------------------------------------------------------------------------


def probe_inner_command() -> str:
    """`/bin/bash -lc` 的正文：逐条 `command -v X` 以 `;` 串联（TD §5.1）。"""
    return "; ".join(f"command -v {c}" for c in PROBE_COMMANDS)


def build_probe_command(timeout_sec: int = PROBE_TIMEOUT_SEC) -> str:
    """生成完整探测命令文本（timeout 注入，TD §5.1/AE §7 超时 15s）。

    形如：`timeout 15 /bin/bash -lc 'command -v bash; command -v pgrep; ...'`
    （timeout 为 GNU coreutils timeout，受控端只读执行，超时退出码 124，
    由 ansible_runner 分类为 TIMEOUT。）
    """
    return (
        f"timeout {timeout_sec} /bin/bash -lc '{probe_inner_command()}'"
    )


# --------------------------------------------------------------------------
# 探测输出解析
# --------------------------------------------------------------------------


def parse_probe_output(output: str) -> Dict[str, bool]:
    """把探测输出解析为能力矩阵 {命令: bool}（TD §5.1 解析规则）。

    规则（TD §5.1）：`command -v X` 成功输出绝对路径 → available；
    非零/无输出 → missing。`command -v` 对缺失命令不产生 stdout 行，
    因此输出行 = 按探测顺序命中的命令路径列表：对每个探测命令，若
    下一个未消费行是绝对路径且 basename 与命令名一致 → available，
    否则 → missing（不消费该行）。

    非绝对路径/命令名不匹配的行不消耗（容忍 PATH 中含非绝对条目等
    边界情况），解析永不抛异常（探测失败按 missing 处理，由
    ansible_runner 依 bash 缺失判定主机 ERROR）。
    """
    import os

    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    result: Dict[str, bool] = {}
    cursor = 0
    for cmd in PROBE_COMMANDS:
        if cursor < len(lines) and lines[cursor].startswith("/") and (
            os.path.basename(lines[cursor]) == cmd
        ):
            result[cmd] = True
            cursor += 1
        else:
            result[cmd] = False
    return result


def probe_status(matrix: Dict[str, bool]) -> str:
    """探测整体状态（AE §3）：bash 缺失或矩阵为空 → failed，否则 ok。

    bash 本身不可用 → 该主机整体 execution_status=ERROR（AE §3），
    由 ansible_runner 据此分类，不产生业务结论。
    """
    if matrix.get("bash", False):
        return PROBE_OK
    return PROBE_FAILED


# --------------------------------------------------------------------------
# 指标 → 所需命令映射（TD §5.2 数据源列只读转写）
# --------------------------------------------------------------------------

# 每条指标采集命令用到的受控端命令（TD §5.2 数据源列 / metrics.py command）；
# 判定依据：命令缺失 → 相关指标 UNKNOWN（error=COMMAND_NOT_FOUND，AE §3）。
# 注：local.logs.key_evidence 模板按 TD §5.2 使用 `egrep`，探测集合（TD §5.1）
# 仅含 `grep`（egrep 为 grep 家族，G0 预检项），故所需命令记 grep。
_METRIC_REQUIRED_COMMANDS: Dict[str, Tuple[str, ...]] = {
    "local.process.present": ("bash", "pgrep", "ps", "grep"),
    "local.service.active": ("bash", "systemctl"),
    "local.port.listening": ("bash", "ss", "grep"),
    "local.cpu.utilization": ("bash", "top", "grep", "tail", "ps", "head"),
    "local.cpu.load_1m": ("bash", "cat", "nproc"),
    "local.memory.available_percent": ("bash", "free"),
    "local.swap.used_percent": ("bash", "free"),
    "local.filesystem.used_percent": ("bash", "df"),
    "local.filesystem.inode_used_percent": ("bash", "df"),
    "local.logs.key_evidence": ("bash", "tail", "grep"),
}


def metric_required_commands(metric_id: str) -> Tuple[str, ...]:
    """某指标采集所需的受控端命令（TD §5.2 数据源列转写）。

    未知指标返回空元组（防御：normalize 等下游不依赖本映射）。
    """
    return _METRIC_REQUIRED_COMMANDS.get(metric_id, ())


def all_probed_commands() -> Tuple[str, ...]:
    """探测命令集合全量（供测试与文档核对）。"""
    return PROBE_COMMANDS


__all__ = [
    "AVAILABLE",
    "MISSING",
    "PROBE_COMMANDS",
    "PROBE_FAILED",
    "PROBE_OK",
    "PROBE_TIMEOUT_SEC",
    "all_probed_commands",
    "build_probe_command",
    "metric_required_commands",
    "parse_probe_output",
    "probe_inner_command",
    "probe_status",
]
